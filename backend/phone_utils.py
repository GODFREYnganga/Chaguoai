"""Country-aware phone normalization (no Firestore dependency)."""

from __future__ import annotations

import re

from geography import dial_code_for_country


def format_to_e164(phone, country_code: str = "+254"):
    """Convert local phone formats (e.g. 07...) to E.164 using the given country prefix."""
    if not phone:
        return phone
    prefix = (country_code or "+254").strip()
    if not prefix.startswith("+"):
        prefix = f"+{prefix}"
    digits_only = re.sub(r"[^\d+]", "", str(phone))
    if digits_only.startswith("+"):
        return digits_only
    national = digits_only.lstrip("0")
    if digits_only.startswith("0"):
        return f"{prefix}{national}"
    prefix_digits = prefix.lstrip("+")
    if digits_only.startswith(prefix_digits):
        return f"+{digits_only}"
    if len(digits_only) <= 10:
        return f"{prefix}{national}"
    return f"+{digits_only}" if not digits_only.startswith("+") else digits_only


def format_client_phone(phone, *, country: str | None = None, country_code: str | None = None):
    """Normalize a client phone; use country name or explicit dial code for local numbers."""
    code = country_code or dial_code_for_country(country)
    return format_to_e164(phone, country_code=code)
