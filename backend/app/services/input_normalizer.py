from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.services.persian_money_engine import normalize_text, parse_persian_money

FUZZY_THRESHOLD = 0.88

ROLE_MAP: dict[str, str] = {
    "کارفرما": "CLIENT",
    "صاحب": "CLIENT",
    "مالک": "CLIENT",
    "مشتری": "CLIENT",
    "کارگر": "WORKER",
    "نیروی کار": "WORKER",
    "دستمزد": "PAYMENT",
    "حقوق": "PAYMENT",
}

ROLE_TOKEN_MAP: dict[str, str] = {
    **ROLE_MAP,
    "روزمزد": "DAILY_WORKER",
    "روز مزد": "DAILY_WORKER",
    "استاد کار": "SKILLED_WORKER",
    "کاشی کار": "SKILLED_WORKER",
    "برق کار": "SKILLED_WORKER",
    "نقاش": "SKILLED_WORKER",
    "رنگ زن": "SKILLED_WORKER",
    "سرامیک کار": "SKILLED_WORKER",
    "جوشکار": "SKILLED_WORKER",
    "ساده": "OTHER",
}

ROLE_PRIORITY = {
    "SKILLED_WORKER": 4,
    "DAILY_WORKER": 3,
    "WORKER": 2,
    "CLIENT": 1,
    "PAYMENT": 0,
}

CONTACT_TERMS = ("شماره تماس", "شماره موبایل", "موبایل", "تلفن")
ACCOUNT_TERMS = ("شماره حساب", "شماره کارت", "حساب", "کارت", "شبا")
VALUE_TERMS = ("دستمزد", "حقوق")
MONEY_TERMS = ("تومان", "تومن", "ریال", "هزار", "میلیون", "میلیارد")
ENTITY_NOISE_TERMS = ("کابینت کار", "گچ کار")
FILLER_TERMS = (
    "است",
    "هست",
    "می باشد",
    "پروژه",
    "به پروژه",
    "در پروژه",
    "برای پروژه",
    "به پروژه اضافه شد",
    "اضافه شد",
    "به",
    "برای",
)


@dataclass(frozen=True)
class NormalizedInput:
    entities: list[dict[str, Any]]
    financials: dict[str, int | str | None]
    facts: list[dict[str, Any]]
    clean_text: str
    name_candidates: list[str]
    role_candidates: list[dict[str, str]]
    amount_candidates: list[int]
    phone_candidates: list[str]
    account_candidates: list[str]
    separator_detected: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "clean_text": self.clean_text,
            "name_candidates": self.name_candidates,
            "role_candidates": self.role_candidates,
            "amount_candidates": self.amount_candidates,
            "phone_candidates": self.phone_candidates,
            "account_candidates": self.account_candidates,
            "separator_detected": self.separator_detected,
            "facts": self.facts,
            "entities": self.entities,
            "financials": self.financials,
        }


def normalize_user_input(raw_text: str) -> dict[str, Any]:
    separator_detected = _has_separator(raw_text)
    clean_text = clean_text_layer(raw_text)
    normalized_text = normalize_tokens(clean_text)
    role_token, role = _extract_role(normalized_text)
    phone = _extract_phone(normalized_text)
    account_number = _extract_account(normalized_text) if not _has_any(normalized_text, CONTACT_TERMS) else None
    amount = _extract_amount(normalized_text, phone=phone, account_number=account_number)
    name = _extract_name(
        normalized_text,
        role_token=role_token if role not in {None, "PAYMENT"} else None,
        values=[phone, account_number, amount],
    )
    name_candidates = [name] if name else []
    role_candidates = _role_candidates(normalized_text)
    amount_candidates = [amount] if amount is not None else []
    phone_candidates = [phone] if phone else []
    account_candidates = [account_number] if account_number else []

    entities: list[dict[str, Any]] = []
    if name:
        entities.append(
            {
                "name": name,
                "type": "PERSON",
                "role": role if role not in {None, "PAYMENT"} else "OTHER",
            }
        )

    facts: list[dict[str, Any]] = []
    if role_token and role:
        facts.append({"type": "ROLE_TOKEN", "token": role_token, "value": role, "entity_name": name})
    if phone:
        facts.append({"type": "PHONE", "value": phone, "entity_name": name})
    if account_number:
        facts.append({"type": "ACCOUNT_NUMBER", "value": account_number, "entity_name": name})
    if amount is not None and _has_any(normalized_text, VALUE_TERMS):
        facts.append({"type": "AMOUNT", "value": amount, "entity_name": name})

    return NormalizedInput(
        entities=entities,
        financials={
            "amount": amount,
            "phone": phone,
            "account_number": account_number,
        },
        facts=facts,
        clean_text=normalized_text,
        name_candidates=name_candidates,
        role_candidates=role_candidates,
        amount_candidates=amount_candidates,
        phone_candidates=phone_candidates,
        account_candidates=account_candidates,
        separator_detected=separator_detected,
    ).as_dict()


def clean_text_layer(raw_text: str) -> str:
    text = normalize_text(raw_text or "")
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = text.replace("\u200c", " ")
    text = re.sub(r"[:：؛;،,\-_/|]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_tokens(clean_text: str) -> str:
    tokens = clean_text.split()
    if not tokens:
        return ""

    normalized: list[str] = []
    index = 0
    max_phrase_len = max(len(token.split()) for token in ROLE_TOKEN_MAP)
    while index < len(tokens):
        replacement = None
        replacement_len = 0
        for phrase_len in range(min(max_phrase_len, len(tokens) - index), 0, -1):
            candidate = " ".join(tokens[index : index + phrase_len])
            canonical = _canonical_token(candidate)
            if canonical is not None:
                replacement = canonical
                replacement_len = phrase_len
                break
        if replacement is None and index + 1 < len(tokens):
            joined = tokens[index] + tokens[index + 1]
            canonical = _canonical_token(joined)
            if canonical is not None:
                replacement = canonical
                replacement_len = 2
        if replacement is None:
            normalized.append(tokens[index])
            index += 1
            continue
        normalized.append(replacement)
        index += replacement_len

    return " ".join(normalized)


def clean_entity_name(value: str | None) -> str | None:
    if not value:
        return None
    name = clean_text_layer(value)
    name = _strip_values(name)
    for token in sorted((*ROLE_TOKEN_MAP.keys(), *ENTITY_NOISE_TERMS), key=len, reverse=True):
        name = name.replace(token, " ")
    for filler in (*CONTACT_TERMS, *ACCOUNT_TERMS, *VALUE_TERMS, *MONEY_TERMS, *FILLER_TERMS):
        name = name.replace(filler, " ")
    name = re.sub(r"[^\u0600-\u06FF\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = _dedupe_name(name)
    if len(name) < 2:
        return None
    return name


def _canonical_token(value: str) -> str | None:
    if value in ROLE_TOKEN_MAP:
        return value
    compact_value = value.replace(" ", "")
    best_token = None
    best_score = 0.0
    for token in ROLE_TOKEN_MAP:
        score = max(
            _similarity(compact_value, token.replace(" ", "")),
            _similarity(_spelling_key(compact_value), _spelling_key(token.replace(" ", ""))),
        )
        if score > best_score:
            best_score = score
            best_token = token
    return best_token if best_token is not None and best_score >= FUZZY_THRESHOLD else None


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def _spelling_key(value: str) -> str:
    return value.replace("گ", "ک")


def _extract_role(text: str) -> tuple[str | None, str | None]:
    detected: list[tuple[str, str]] = []
    for token, role in sorted(ROLE_TOKEN_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if role == "PAYMENT":
            continue
        if token in text.split() or token in text:
            detected.append((token, role))
    if not detected:
        return None, None
    return max(detected, key=lambda item: (ROLE_PRIORITY.get(item[1], 0), len(item[0])))


def _role_candidates(text: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for token, role in sorted(ROLE_TOKEN_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if role == "PAYMENT":
            continue
        if token in text.split() or token in text:
            candidates.append({"token": token, "project_role": _contract_role(role)})
    return candidates


def _contract_role(role: str) -> str:
    if role == "WORKER":
        return "DAILY_WORKER"
    if role in {"CLIENT", "VENDOR", "DAILY_WORKER", "SKILLED_WORKER", "OTHER"}:
        return role
    return "OTHER"


def _extract_name(
    text: str,
    *,
    role_token: str | None,
    values: list[str | int | None],
) -> str | None:
    candidates = [text]
    if role_token and role_token in text:
        before, after = text.split(role_token, 1)
        candidates = [before, after, text]
    for candidate in candidates:
        extracted = _extract_name_from_candidate(candidate, values=values)
        if extracted:
            return extracted
    return None


def _extract_name_from_candidate(
    candidate: str,
    *,
    values: list[str | int | None],
) -> str | None:
    for term in sorted((*ROLE_TOKEN_MAP.keys(), *ENTITY_NOISE_TERMS), key=len, reverse=True):
        candidate = candidate.replace(term, " ")
    for term in (*CONTACT_TERMS, *ACCOUNT_TERMS, *VALUE_TERMS, *MONEY_TERMS):
        candidate = candidate.replace(term, " ")
    for value in values:
        if value is not None:
            candidate = candidate.replace(str(value), " ")
    return clean_entity_name(_last_persian_name_segment(candidate))


def _extract_phone(text: str) -> str | None:
    if not _has_any(text, CONTACT_TERMS):
        return None
    compact = re.sub(r"\s+", "", text)
    match = re.search(r"09\d{5,12}", compact)
    return match.group() if match else None


def _extract_account(text: str) -> str | None:
    if not _has_any(text, ACCOUNT_TERMS):
        return None
    compact = re.sub(r"\s+", "", text)
    match = re.search(r"\d{8,26}", compact)
    return match.group() if match else None


def _extract_amount(text: str, *, phone: str | None, account_number: str | None) -> int | None:
    if (phone or account_number) and not _has_any(text, VALUE_TERMS):
        return None
    amount = parse_persian_money(text)
    if amount is not None:
        return int(amount)
    match = re.search(r"\d{4,}", re.sub(r"\s+", "", text))
    return int(match.group()) if match else None


def _strip_values(text: str) -> str:
    return re.sub(r"\d+", " ", text)


def _dedupe_name(name: str) -> str:
    parts = name.split()
    if not parts:
        return ""
    if len(parts) % 2 == 0:
        midpoint = len(parts) // 2
        if parts[:midpoint] == parts[midpoint:]:
            return " ".join(parts[:midpoint])
    deduped: list[str] = []
    for part in parts:
        if not deduped or deduped[-1] != part:
            deduped.append(part)
    return " ".join(deduped)


def _last_persian_name_segment(value: str) -> str:
    segments = [
        segment.strip()
        for segment in re.findall(r"[\u0600-\u06FF]+(?:\s+[\u0600-\u06FF]+)*", value)
        if segment.strip()
    ]
    return segments[-1] if segments else ""


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _has_separator(text: str) -> bool:
    return bool(re.search(r"[:：؛;،,\-_/|]", text or ""))
