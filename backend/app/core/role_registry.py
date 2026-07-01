from __future__ import annotations

from typing import Any

from app.services.persian_money_engine import normalize_text


ROLE_REGISTRY: list[dict[str, Any]] = [
    {
        "key": "CLIENT",
        "labels": ["کارفرما", "کار فرما", "کارفرمای پروژه", "مالک", "مالک پروژه", "صاحب کار", "مشتری"],
        "category": "CLIENT",
        "worker_type": "CLIENT",
        "priority": 10,
    },
    {
        "key": "VENDOR",
        "labels": ["فروشنده", "تامین کننده", "تأمین کننده", "مغازه دار", "وندور"],
        "category": "VENDOR",
        "worker_type": "VENDOR",
        "priority": 6,
    },
    {
        "key": "SKILLED_WORKER",
        "labels": [
            "نقاش",
            "رنگ کار",
            "رنگکار",
            "رنگ‌کار",
            "رنگ زن",
            "گچ کار",
            "گچکار",
            "گچ‌کار",
            "کابینت کار",
            "کناف کار",
            "نما کار",
            "جوشکار",
            "جوشکاری",
            "برقکار",
            "برق کار",
            "لوله کش",
            "لولهکش",
            "لوله‌کش",
            "تاسیساتی",
            "کاشی کار",
            "سرامیک کار",
            "سرامیککار",
            "سرامیک‌کار",
            "سنگ کار",
            "سنگکار",
            "سنگ‌کار",
            "welder",
            "electrician",
            "plumber",
            "painter",
            "tiler",
        ],
        "category": "SKILLED_WORKER",
        "worker_type": "SKILLED_WORKER",
        "priority": 7,
    },
    {
        "key": "GENERAL_WORKER",
        "labels": ["کارگر", "کارگر ساده", "کارگر روزمزد", "روزمزد", "روز مزد", "نیروی کار"],
        "category": "GENERAL_WORKER",
        "worker_type": "DAILY_WORKER",
        "priority": 5,
    },
    {
        "key": "MANAGER",
        "labels": [],
        "category": "MANAGER",
        "worker_type": "OTHER",
        "priority": 4,
    },
]

ROLE_ALIASES: dict[str, str] = {
    "SKILLED": "SKILLED_WORKER",
    "WORKER": "GENERAL_WORKER",
    "DAILY_WORKER": "GENERAL_WORKER",
    "OTHER": "MANAGER",
}


def normalized_role_labels() -> dict[str, str]:
    labels: dict[str, str] = {}
    for role in ROLE_REGISTRY:
        key = str(role["key"])
        for label in role.get("labels", []):
            labels[normalize_role_label(str(label))] = key
    return labels


def role_token_map() -> dict[str, str]:
    return {
        label: registry_key_to_project_role(key)
        for label, key in normalized_role_labels().items()
    }


def registry_key_to_project_role(key: str | None) -> str:
    if not key:
        return "OTHER"
    normalized_key = ROLE_ALIASES.get(str(key), str(key))
    for role in ROLE_REGISTRY:
        if role["key"] == normalized_key:
            return str(role.get("worker_type") or role.get("category") or "OTHER")
    if normalized_key in {"CLIENT", "VENDOR", "DAILY_WORKER", "SKILLED_WORKER", "OTHER"}:
        return normalized_key
    return "OTHER"


def normalize_role_label(value: str) -> str:
    return normalize_text(value or "").replace("\u200c", " ").strip()


def detect_role_label(text: str | None) -> tuple[str, str] | None:
    if not text:
        return None
    normalized = normalize_role_label(text)
    matches = []
    for label, key in normalized_role_labels().items():
        if label and label in normalized:
            role = next(item for item in ROLE_REGISTRY if item["key"] == key)
            matches.append((label, key, int(role.get("priority", 0))))
    if not matches:
        return None
    label, key, _priority = max(matches, key=lambda item: (item[2], len(item[0])))
    return label, registry_key_to_project_role(key)


def labels_for_project_role(project_role: str) -> list[str]:
    labels: list[str] = []
    for role in ROLE_REGISTRY:
        if registry_key_to_project_role(str(role["key"])) == project_role:
            labels.extend(str(label) for label in role.get("labels", []))
    return labels


def is_skilled_role_text(value: str | None) -> bool:
    detected = detect_role_label(value)
    return detected is not None and detected[1] == "SKILLED_WORKER"


def frontend_role_options() -> list[dict[str, str]]:
    return [
        {"value": "CLIENT", "label": "کارفرما"},
        {"value": "DAILY_WORKER", "label": "کارگر"},
        {"value": "VENDOR", "label": "فروشنده"},
        {"value": "SKILLED_WORKER", "label": "استادکار"},
        {"value": "OTHER", "label": "سایر"},
    ]


def role_label_for_worker_type(worker_type: str | None) -> str:
    if not worker_type:
        return "نامشخص"
    for option in frontend_role_options():
        if option["value"] == worker_type:
            return option["label"]
    return worker_type


def project_role_values() -> set[str]:
    return {option["value"] for option in frontend_role_options()}
