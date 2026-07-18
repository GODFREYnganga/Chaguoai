"""
Analytics-only geography: country and administrative region capture.

These fields are excluded from WHO MEC assessment and clinical LLM prompts.
Used for dashboards, reporting, and program geography — not method eligibility.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any, Optional

# Canonical African countries (ISO-oriented names, English)
AFRICAN_COUNTRIES: tuple[str, ...] = (
    "Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi",
    "Cabo Verde", "Cameroon", "Central African Republic", "Chad", "Comoros",
    "Congo", "Cote d'Ivoire", "Democratic Republic of the Congo", "Djibouti",
    "Egypt", "Equatorial Guinea", "Eritrea", "Eswatini", "Ethiopia", "Gabon",
    "Gambia", "Ghana", "Guinea", "Guinea-Bissau", "Kenya", "Lesotho",
    "Liberia", "Libya", "Madagascar", "Malawi", "Mali", "Mauritania",
    "Mauritius", "Morocco", "Mozambique", "Namibia", "Niger", "Nigeria",
    "Rwanda", "Sao Tome and Principe", "Senegal", "Seychelles", "Sierra Leone",
    "Somalia", "South Africa", "South Sudan", "Sudan", "Tanzania", "Togo",
    "Tunisia", "Uganda", "Zambia", "Zimbabwe",
)

# E.164 dial prefixes for African countries in AFRICAN_COUNTRIES (analytics / phone normalization).
COUNTRY_DIAL_CODES: dict[str, str] = {
    "Algeria": "+213",
    "Angola": "+244",
    "Benin": "+229",
    "Botswana": "+267",
    "Burkina Faso": "+226",
    "Burundi": "+257",
    "Cabo Verde": "+238",
    "Cameroon": "+237",
    "Central African Republic": "+236",
    "Chad": "+235",
    "Comoros": "+269",
    "Congo": "+242",
    "Cote d'Ivoire": "+225",
    "Democratic Republic of the Congo": "+243",
    "Djibouti": "+253",
    "Egypt": "+20",
    "Equatorial Guinea": "+240",
    "Eritrea": "+291",
    "Eswatini": "+268",
    "Ethiopia": "+251",
    "Gabon": "+241",
    "Gambia": "+220",
    "Ghana": "+233",
    "Guinea": "+224",
    "Guinea-Bissau": "+245",
    "Kenya": "+254",
    "Lesotho": "+266",
    "Liberia": "+231",
    "Libya": "+218",
    "Madagascar": "+261",
    "Malawi": "+265",
    "Mali": "+223",
    "Mauritania": "+222",
    "Mauritius": "+230",
    "Morocco": "+212",
    "Mozambique": "+258",
    "Namibia": "+264",
    "Niger": "+227",
    "Nigeria": "+234",
    "Rwanda": "+250",
    "Sao Tome and Principe": "+239",
    "Senegal": "+221",
    "Seychelles": "+248",
    "Sierra Leone": "+232",
    "Somalia": "+252",
    "South Africa": "+27",
    "South Sudan": "+211",
    "Sudan": "+249",
    "Tanzania": "+255",
    "Togo": "+228",
    "Tunisia": "+216",
    "Uganda": "+256",
    "Zambia": "+260",
    "Zimbabwe": "+263",
}

ADMIN_AREA_LABELS: dict[str, str] = {
    "Kenya": "county",
    "South Africa": "province",
    "Nigeria": "state",
    "Ethiopia": "region",
    "Uganda": "district",
    "Tanzania": "region",
    "Rwanda": "district",
    "Ghana": "region",
    "Zambia": "province",
    "Zimbabwe": "province",
    "Malawi": "district",
    "Mozambique": "province",
    "Democratic Republic of the Congo": "province",
}

ANALYTICS_ONLY_FIELDS: frozenset[str] = frozenset({
    "country",
    "country_raw",
    "country_match_confidence",
    "admin_area",
    "admin_area_raw",
    "admin_area_type",
    "location_capture_purpose",
    "location_captured_at",
    "location_source",
    "pending_country",
    "pending_country_raw",
    "pending_country_match_confidence",
})

MATCH_EXACT = "exact"
MATCH_ALIAS = "alias"
MATCH_FUZZY = "fuzzy"
MATCH_UNMATCHED = "unmatched"

FUZZY_AUTO_THRESHOLD = 0.92
FUZZY_SUGGEST_THRESHOLD = 0.75

_OTHER_COUNTRY = "Other"
_MIN_INPUT_LEN = 2
_MAX_INPUT_LEN = 80

_JUNK_PATTERN = re.compile(
    r"^(test|asdf|xxx|none|n/a|na|\.+|-+|ok|hi|hello)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NormalizedCountry:
    raw: str
    canonical: str
    confidence: str
    needs_confirmation: bool


def _data_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _load_aliases() -> dict[str, str]:
    path = os.path.join(_data_dir(), "geography_aliases.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        aliases = data.get("country_aliases", {})
        return {k.lower().strip(): v for k, v in aliases.items() if v}
    except (OSError, json.JSONDecodeError):
        return {}


_ALIASES: dict[str, str] = _load_aliases()
_LOWER_TO_CANONICAL: dict[str, str] = {c.lower(): c for c in AFRICAN_COUNTRIES}


def dial_code_for_country(country: Optional[str], default: str = "+254") -> str:
    """Return E.164 country prefix for a canonical or fuzzy country name."""
    if not country:
        return default
    canonical = normalize_country(str(country), allow_legacy_index=False).canonical
    if canonical == _OTHER_COUNTRY:
        return default
    return COUNTRY_DIAL_CODES.get(canonical, default)


def admin_area_label(country: Optional[str]) -> str:
    if not country:
        return "county/state/district"
    return ADMIN_AREA_LABELS.get(country, "county/state/district")


def strip_location_input(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())[:_MAX_INPUT_LEN]


def is_valid_location_input(text: str) -> bool:
    cleaned = strip_location_input(text)
    if len(cleaned) < _MIN_INPUT_LEN:
        return False
    if _JUNK_PATTERN.match(cleaned):
        return False
    if re.fullmatch(r"\d+", cleaned):
        return False
    return True


def is_valid_country_input(text: str) -> bool:
    """Country step: allow legacy 1–54 menu index or free-text country name."""
    cleaned = strip_location_input(text)
    if cleaned.isdigit():
        idx = int(cleaned) - 1
        return 0 <= idx < len(AFRICAN_COUNTRIES)
    return is_valid_location_input(text)


def normalize_country(raw: str, *, allow_legacy_index: bool = True) -> NormalizedCountry:
    """
    Map free text (or legacy 1–54 menu index) to a canonical country name.

    Returns needs_confirmation=True for fuzzy matches so WhatsApp can ask the user.
    """
    text = strip_location_input(raw)
    if not text:
        return NormalizedCountry("", _OTHER_COUNTRY, MATCH_UNMATCHED, False)

    if allow_legacy_index and text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(AFRICAN_COUNTRIES):
            canonical = AFRICAN_COUNTRIES[idx]
            return NormalizedCountry(text, canonical, MATCH_EXACT, False)

    lowered = text.lower()
    if lowered in _LOWER_TO_CANONICAL:
        return NormalizedCountry(text, _LOWER_TO_CANONICAL[lowered], MATCH_EXACT, False)

    if lowered in _ALIASES:
        return NormalizedCountry(text, _ALIASES[lowered], MATCH_ALIAS, False)

    close = get_close_matches(lowered, list(_LOWER_TO_CANONICAL.keys()), n=1, cutoff=FUZZY_SUGGEST_THRESHOLD)
    if close:
        canonical = _LOWER_TO_CANONICAL[close[0]]
        ratio = _similarity_ratio(lowered, close[0])
        if ratio >= FUZZY_AUTO_THRESHOLD:
            return NormalizedCountry(text, canonical, MATCH_FUZZY, True)
        return NormalizedCountry(text, canonical, MATCH_FUZZY, True)

    return NormalizedCountry(text, _OTHER_COUNTRY, MATCH_UNMATCHED, False)


def _similarity_ratio(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def normalize_admin_area(raw: str, country: Optional[str] = None) -> str:
    """Title-case region text; no gazetteer validation at v1."""
    text = strip_location_input(raw)
    if not text:
        return ""
    if text.islower() or text.isupper():
        return text.title()
    return text


def country_prompt(lang: str) -> str:
    prompts = {
        "english": (
            "For analytics only (this does *not* affect your Method Match): "
            "which country are you in? Reply with the country name, e.g. Kenya, Nigeria, South Africa."
        ),
        "swahili": (
            "Kwa takwimu tu (haitaathiri mapendekezo yako): uko nchi gani? "
            "Jibu kwa jina la nchi, mf. Kenya, Nigeria, Afrika Kusini."
        ),
        "french": (
            "Pour les statistiques uniquement (cela n'affecte pas votre recommandation) : "
            "dans quel pays etes-vous ? Repondez avec le nom du pays, ex. Kenya, Nigeria."
        ),
        "portuguese": (
            "Apenas para analise (nao afeta sua recomendacao): em qual pais voce esta? "
            "Responda com o nome do pais, ex. Quenia, Nigeria, Africa do Sul."
        ),
    }
    return prompts.get(lang, prompts["english"])


def admin_area_prompt(lang: str, country: str) -> str:
    label = admin_area_label(country)
    prompts = {
        "english": f"For analytics only, which {label} are you in? Reply with the name (e.g. Nairobi, Lagos State).",
        "swahili": f"Kwa takwimu tu, uko {label} gani? Jibu kwa jina (mf. Nairobi, Mombasa).",
        "french": f"Pour les statistiques uniquement, dans quel(le) {label} etes-vous ? Repondez par le nom.",
        "portuguese": f"Apenas para analise, em qual {label} voce esta? Responda com o nome.",
    }
    return prompts.get(lang, prompts["english"])


def country_confirm_prompt(lang: str, canonical: str) -> str:
    prompts = {
        "english": f"We understood your country as *{canonical}*. Reply *1* to confirm or *2* to type your country again.",
        "swahili": f"Tumechukulia nchi yako kuwa *{canonical}*. Jibu *1* kuthibitisha au *2* kuandika tena.",
        "french": f"Nous avons compris : *{canonical}*. Repondez *1* pour confirmer ou *2* pour ressaisir.",
        "portuguese": f"Entendemos seu pais como *{canonical}*. Responda *1* para confirmar ou *2* para digitar de novo.",
    }
    return prompts.get(lang, prompts["english"])


def invalid_location_prompt(lang: str, field: str = "country") -> str:
    if field == "admin_area":
        msgs = {
            "english": "Please enter a valid region name (at least 2 characters).",
            "swahili": "Tafadhali andika eneo halali (angalau herufi 2).",
            "french": "Veuillez entrer un nom de region valide (au moins 2 caracteres).",
            "portuguese": "Digite um nome de regiao valido (pelo menos 2 caracteres).",
        }
    else:
        msgs = {
            "english": "Please enter a valid country name (e.g. Kenya). At least 2 characters.",
            "swahili": "Tafadhali andika jina la nchi halali (mf. Kenya). Angalau herufi 2.",
            "french": "Veuillez entrer un nom de pays valide (ex. Kenya). Au moins 2 caracteres.",
            "portuguese": "Digite um nome de pais valido (ex. Quenia). Pelo menos 2 caracteres.",
        }
    return msgs.get(lang, msgs["english"])


def build_country_firestore_fields(
    normalized: NormalizedCountry,
    *,
    source: str,
) -> dict[str, Any]:
    return {
        "country_raw": normalized.raw,
        "country": normalized.canonical,
        "country_match_confidence": normalized.confidence,
        "location_capture_purpose": "analytics_only",
        "location_source": source,
    }


def build_admin_area_firestore_fields(
    raw: str,
    country: str,
    *,
    source: str,
) -> dict[str, Any]:
    return {
        "admin_area_raw": strip_location_input(raw),
        "admin_area": normalize_admin_area(raw, country),
        "admin_area_type": admin_area_label(country),
        "location_capture_purpose": "analytics_only",
        "location_source": source,
    }


def strip_analytics_fields(data: dict) -> dict:
    """Remove geography fields before clinical prompts or MEC mapping."""
    return {k: v for k, v in data.items() if k not in ANALYTICS_ONLY_FIELDS}


def countries_for_api() -> list[dict[str, str]]:
    """JSON-serializable list for provider portal dropdown."""
    return [{"name": c, "admin_area_label": admin_area_label(c)} for c in AFRICAN_COUNTRIES]


def aggregate_geography_stats(users: list[dict]) -> dict[str, Any]:
    """Build geography breakdowns from contraceptive_users documents."""
    by_country: dict[str, int] = {}
    by_region: dict[str, dict[str, int]] = {}
    unmatched = 0
    with_location = 0

    for data in users:
        country = data.get("country") or ""
        if not country:
            continue
        with_location += 1
        by_country[country] = by_country.get(country, 0) + 1
        if data.get("country_match_confidence") == MATCH_UNMATCHED:
            unmatched += 1
        area = data.get("admin_area") or ""
        if area and country:
            bucket = by_region.setdefault(country, {})
            bucket[area] = bucket.get(area, 0) + 1

    top_countries = sorted(by_country.items(), key=lambda x: -x[1])[:15]
    top_regions: dict[str, list[tuple[str, int]]] = {}
    for country, _ in top_countries[:5]:
        regions = by_region.get(country, {})
        top_regions[country] = sorted(regions.items(), key=lambda x: -x[1])[:10]

    total_with_country = with_location or 1
    return {
        "clients_with_location": with_location,
        "by_country": dict(top_countries),
        "top_regions_by_country": {k: dict(v) for k, v in top_regions.items()},
        "unmatched_country_count": unmatched,
        "unmatched_rate_percent": round(100 * unmatched / total_with_country, 1) if with_location else 0,
    }
