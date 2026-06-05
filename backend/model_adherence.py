"""
ChaguoAI adherence/discontinuation model serving helpers.

This model is intentionally downstream of WHO MEC safety filtering. It ranks or
annotates MEC-safe methods by predicted continuation support need; it never
decides clinical eligibility.
"""

from __future__ import annotations

import json
import os
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from method_library import normalize_method_key


TRAINED_METHOD_NAMES = {
    "injectable": "Injectables",
    "pill": "Pills",
    "implant": "Implants",
    "iud": "IUCD",
    "condom": "Condoms",
    "sterilization": "BTL",
}

METHOD_CATEGORY_MAP = {
    "Injectables": "short_acting_hormonal",
    "Pills": "short_acting_hormonal",
    "Pills & Condoms": "short_acting_hormonal",
    "Implants": "long_acting_reversible",
    "IUCD": "long_acting_reversible",
    "BTL": "permanent",
    "Condoms": "barrier",
}

EDUCATION_ORDINAL = {
    "Primary Incomplete": 1,
    "Primary Complete": 2,
    "Secondary & Above": 3,
}

FERTILITY_ORDINAL = {
    "Within 2 Years": 1,
    "Later than 2 years": 2,
    "No more Children": 3,
}

COUNSELED_BINARY = {"Yes": 1, "Refreshers": 1, "No": 0}
VALIDATED_COUNTIES = {"busia", "siaya"}
DEFAULT_THRESHOLD = 0.3916


@dataclass
class AdherenceAssets:
    model: Any
    encoders: dict[str, Any]
    feature_names: list[str]
    metadata: dict[str, Any]
    loaded: bool
    reason: str = ""


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_model_root() -> Path:
    return _project_root() / "chaguoai_model" / "outputs"


def model_paths() -> dict[str, Path]:
    root = Path(os.getenv("CHAGUOAI_ADHERENCE_MODEL_DIR", str(_default_model_root())))
    return {
        "root": root,
        "model": root / "models" / "05_best_model.pkl",
        "encoders": root / "processed" / "04_encoders.pkl",
        "feature_meta": root / "processed" / "04_feature_meta.json",
        "metadata": root / "models" / "05_best_model_metadata.json",
    }


@lru_cache(maxsize=1)
def load_adherence_assets() -> AdherenceAssets:
    paths = model_paths()
    try:
        import pandas  # noqa: F401
        import lightgbm  # noqa: F401
    except Exception as exc:
        return AdherenceAssets(None, {}, [], {}, False, f"missing_dependency:{exc}")

    missing = [name for name, path in paths.items() if name != "root" and not path.exists()]
    if missing:
        return AdherenceAssets(None, {}, [], {}, False, f"missing_artifacts:{','.join(missing)}")

    try:
        with open(paths["model"], "rb") as f:
            model = pickle.load(f)
        with open(paths["encoders"], "rb") as f:
            encoders = pickle.load(f)
        with open(paths["feature_meta"], encoding="utf-8") as f:
            feature_meta = json.load(f)
        with open(paths["metadata"], encoding="utf-8") as f:
            metadata = json.load(f)
        return AdherenceAssets(
            model=model,
            encoders=encoders,
            feature_names=feature_meta.get("final_model_features") or metadata.get("features", {}).get("feature_names") or [],
            metadata=metadata,
            loaded=True,
        )
    except Exception as exc:
        return AdherenceAssets(None, {}, [], {}, False, f"load_failed:{exc}")


def _first_int(*values: Any, default: int = 0) -> int:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(str(value).strip().split()[0])
        except Exception:
            digits = "".join(ch for ch in str(value) if ch.isdigit())
            if digits:
                return int(digits)
    return default


def _norm_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _education_level(client: dict[str, Any], imputed: list[str]) -> str:
    text = _norm_text(client.get("education_level") or client.get("educationlevel"))
    if any(token in text for token in ("secondary", "college", "university", "above")):
        return "Secondary & Above"
    if "incomplete" in text:
        return "Primary Incomplete"
    if text:
        return "Primary Complete"
    imputed.append("education_level")
    return "Primary Complete"


def _fertility_intention(client: dict[str, Any], imputed: list[str]) -> str:
    text = _norm_text(client.get("more_children") or client.get("future_children") or client.get("fertility_intention"))
    if any(token in text for token in ("1", "soon", "within", "2 year", "karibuni")):
        return "Within 2 Years"
    if any(token in text for token in ("3", "no more", "none", "hapana", "no")):
        return "No more Children"
    if any(token in text for token in ("2", "later", "baadaye")):
        return "Later than 2 years"
    imputed.append("fertility_intention")
    return "Later than 2 years"


def _delivery_type(client: dict[str, Any], imputed: list[str]) -> str:
    text = _norm_text(client.get("delivery_type") or client.get("delivery"))
    if any(token in text for token in ("household", "outreach", "community")):
        return "community"
    if any(token in text for token in ("facility", "clinic", "hospital")):
        return "facility"
    imputed.append("delivery_type")
    return "facility"


def _previous_method(client: dict[str, Any], imputed: list[str]) -> str:
    raw = client.get("previous_method") or client.get("previousmethod") or client.get("last_method")
    if raw:
        mapped = TRAINED_METHOD_NAMES.get(normalize_method_key(raw))
        return mapped or str(raw)
    if _norm_text(client.get("previous_use")) in {"2", "no", "none", "hapana"}:
        return "unknown"
    imputed.append("previous_method")
    return "unknown"


def _candidate_method(method_name: str) -> str | None:
    return TRAINED_METHOD_NAMES.get(normalize_method_key(method_name))


def _switch_type(curr: str, prev: str) -> str:
    prev_cat = METHOD_CATEGORY_MAP.get(prev, "unknown")
    curr_cat = METHOD_CATEGORY_MAP.get(curr, "unknown")
    if prev_cat == "unknown":
        return "unknown"
    if curr_cat == prev_cat:
        return "same_category"
    if prev_cat == "long_acting_reversible" and curr_cat != "long_acting_reversible":
        return "downgraded_from_larc"
    if curr_cat == "long_acting_reversible" and prev_cat != "long_acting_reversible":
        return "upgraded_to_larc"
    if curr_cat == "permanent":
        return "moved_to_permanent"
    if curr_cat == "barrier":
        return "moved_to_barrier"
    return "lateral_switch"


def map_client_to_model_profile(client: dict[str, Any], candidate_method: str) -> dict[str, Any]:
    imputed: list[str] = []
    unsupported: list[str] = []
    trained_method = _candidate_method(candidate_method)
    if not trained_method:
        unsupported.append("candidate_method")
        trained_method = "UNKNOWN"

    age = _first_int(client.get("age"), default=25)
    if not client.get("age"):
        imputed.append("age")
    children = _first_int(client.get("living_children"), client.get("parity"), client.get("noofchildren"), default=1)
    if not (client.get("living_children") or client.get("parity") or client.get("noofchildren")):
        imputed.append("noofchildren")

    education = _education_level(client, imputed)
    fertility = _fertility_intention(client, imputed)
    previous = _previous_method(client, imputed)
    delivery = _delivery_type(client, imputed)
    county = str(client.get("admin_area") or client.get("county") or "UNKNOWN").strip() or "UNKNOWN"
    country = str(client.get("country") or "").strip()
    now = datetime.now(timezone.utc)

    applicability = "validated_geography" if country.lower() == "kenya" and county.lower() in VALIDATED_COUNTIES else "out_of_distribution"
    if unsupported:
        applicability = "insufficient_data"

    return {
        "row": {
            "age": age,
            "noofchildren": min(children, 15),
            "education_ordinal": EDUCATION_ORDINAL.get(education, 2),
            "fertility_ordinal": FERTILITY_ORDINAL.get(fertility, 2),
            "month_num": _first_int(client.get("month_num"), client.get("month"), default=now.month),
            "year": _first_int(client.get("year"), default=now.year),
            "is_young_woman": int(age < 20),
            "is_older_woman": int(age >= 40),
            "has_high_parity": int(children >= 5),
            "wants_child_soon": int(fertility == "Within 2 Years"),
            "wants_no_more": int(fertility == "No more Children"),
            "was_on_larc": int(METHOD_CATEGORY_MAP.get(previous) == "long_acting_reversible"),
            "adopted_larc": int(METHOD_CATEGORY_MAP.get(trained_method) == "long_acting_reversible"),
            "counseled_binary": COUNSELED_BINARY.get(client.get("counseled") or "Yes", 1),
            "fertility_intention_known": int("fertility_intention" not in imputed),
            "education_known": int("education_level" not in imputed),
            "county": county if county.lower() in VALIDATED_COUNTIES else "UNKNOWN",
            "delivery_type": delivery,
            "previous_method_category": METHOD_CATEGORY_MAP.get(previous, "unknown"),
            "current_method_category": METHOD_CATEGORY_MAP.get(trained_method, "unknown"),
            "switch_type": _switch_type(trained_method, previous),
        },
        "candidate_method": trained_method,
        "previous_method": previous,
        "imputed_fields": imputed,
        "unsupported_fields": unsupported,
        "model_applicability": applicability,
    }


def _encode_value(encoder: Any, value: Any) -> int:
    if encoder is None:
        return 0
    classes = set(getattr(encoder, "classes_", []))
    encoded = str(value)
    if encoded not in classes:
        encoded = "UNKNOWN" if "UNKNOWN" in classes else "unknown" if "unknown" in classes else next(iter(classes), encoded)
    return int(encoder.transform([encoded])[0])


def build_feature_frame(profile: dict[str, Any], assets: AdherenceAssets):
    import pandas as pd

    row = dict(profile["row"])
    for cat_col in ["county", "delivery_type", "previous_method_category", "current_method_category", "switch_type"]:
        row[f"{cat_col}_enc"] = _encode_value(assets.encoders.get(cat_col), row.get(cat_col))
    for feature in assets.feature_names:
        row.setdefault(feature, 0)
    return pd.DataFrame([row])[assets.feature_names].fillna(0)


def _risk_level(discontinuation_probability: float, threshold: float) -> str:
    if discontinuation_probability >= threshold:
        return "high"
    if discontinuation_probability >= threshold * 0.6:
        return "moderate"
    return "low"


def _support_reasons(profile: dict[str, Any], method_name: str) -> list[str]:
    row = profile.get("row", {})
    reasons = []
    if row.get("wants_child_soon"):
        reasons.append("Client may want pregnancy soon, so continuation may need extra counseling.")
    if row.get("has_high_parity") or row.get("wants_no_more"):
        reasons.append("Parity and fertility intention affect continuation patterns.")
    if row.get("switch_type") in {"downgraded_from_larc", "upgraded_to_larc", "moved_to_barrier"}:
        reasons.append("Previous method pattern may affect continuation.")
    if normalize_method_key(method_name) in {"pill", "condom"}:
        reasons.append("This method needs consistent user action.")
    if profile.get("model_applicability") != "validated_geography":
        reasons.append("Model was trained in Siaya/Busia, so use this score as support guidance only.")
    if profile.get("imputed_fields"):
        reasons.append("Some model inputs were imputed from defaults.")
    return reasons[:4] or ["Predicted from age, parity, fertility intention, geography, and method history."]


def predict_method_adherence(client: dict[str, Any], method_name: str, assets: AdherenceAssets | None = None) -> dict[str, Any]:
    assets = assets or load_adherence_assets()
    profile = map_client_to_model_profile(client, method_name)
    version = assets.metadata.get("model_version") or assets.metadata.get("model_name") or ""
    threshold = assets.metadata.get("validation_performance", {}).get("optimal_threshold", DEFAULT_THRESHOLD)
    base = {
        "model_name": assets.metadata.get("model_name") or "lightgbm",
        "model_version": version,
        "model_applicability": profile["model_applicability"],
        "imputed_fields": profile["imputed_fields"],
        "unsupported_fields": profile["unsupported_fields"],
    }
    if not assets.loaded:
        return {
            **base,
            "available": False,
            "reason": assets.reason,
            "adherence_score": None,
            "discontinuation_probability": None,
            "adherence_risk_level": "unknown",
            "adherence_reasons": ["Adherence model is not available in this environment."],
        }
    if profile["unsupported_fields"]:
        return {
            **base,
            "available": False,
            "reason": "unsupported_method",
            "adherence_score": None,
            "discontinuation_probability": None,
            "adherence_risk_level": "unknown",
            "adherence_reasons": ["This method is outside the trained model method set."],
        }

    features = build_feature_frame(profile, assets)
    discontinuation_probability = float(assets.model.predict_proba(features)[0, 1])
    adherence_score = 1.0 - discontinuation_probability
    risk = _risk_level(discontinuation_probability, float(threshold))
    return {
        **base,
        "available": True,
        "adherence_score": round(adherence_score, 4),
        "discontinuation_probability": round(discontinuation_probability, 4),
        "adherence_risk_level": risk,
        "continuation_support_needed": {"low": "Low", "moderate": "Medium", "high": "High"}[risk],
        "adherence_reasons": _support_reasons(profile, method_name),
    }
