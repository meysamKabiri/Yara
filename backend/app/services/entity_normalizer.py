import re

from app.services.persian_money_engine import normalize_text

TITLE_PATTERN = re.compile(r"^(آقای|اقای|خانم|مهندس|استاد|حاج|مش|جناب)\s+")


def normalize_name(text: str) -> str:
    normalized = normalize_text(text).replace("\u200c", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    while True:
        without_title = TITLE_PATTERN.sub("", normalized).strip()
        if without_title == normalized:
            return normalized
        normalized = without_title


def compact_name(text: str) -> str:
    return normalize_name(text).replace(" ", "")


def match_score(a: str, b: str) -> float:
    normalized_a = normalize_name(a)
    normalized_b = normalize_name(b)
    if not normalized_a or not normalized_b:
        return 0.0
    if normalized_a == normalized_b:
        return 1.0
    compact_a = compact_name(a)
    compact_b = compact_name(b)
    if compact_a == compact_b:
        return 0.95
    if normalized_a in normalized_b or normalized_b in normalized_a:
        return 0.7
    if compact_a in compact_b or compact_b in compact_a:
        return 0.7
    return 0.0
