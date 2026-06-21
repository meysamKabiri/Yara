import re

from app.services.persian_money_engine import normalize_text


def generate_identity_key(name: str, phone: str | None) -> str:
    normalized_name = _normalize_identity_name(name)
    normalized_phone = _normalize_identity_phone(phone)
    if normalized_phone:
        return f"{normalized_name}|{normalized_phone}"
    return normalized_name


def _normalize_identity_name(name: str) -> str:
    normalized = normalize_text(name).replace("\u200c", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return normalized


def _normalize_identity_phone(phone: str | None) -> str | None:
    if phone is None:
        return None
    normalized = normalize_text(phone)
    digits = re.sub(r"\D+", "", normalized)
    return digits or None
