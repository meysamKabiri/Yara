from enum import StrEnum
from typing import Any

from app.services.compare_legacy_vs_shadow import compare_legacy_vs_shadow


class ShadowConflictType(StrEnum):
    ENTITY_MISMATCH = "ENTITY_MISMATCH"
    INTENT_MISMATCH = "INTENT_MISMATCH"
    AMOUNT_ERROR = "AMOUNT_ERROR"
    DIRECTION_ERROR = "DIRECTION_ERROR"
    MISSING_ENTITY = "MISSING_ENTITY"
    OVERCONFIDENCE_ERROR = "OVERCONFIDENCE_ERROR"


def analyze_shadow_conflict(
    legacy_json: dict[str, Any] | list[dict[str, Any]],
    shadow_json: dict[str, Any],
    diff_json: dict[str, Any] | None = None,
    high_confidence_threshold: float = 0.8,
) -> list[str]:
    diff = diff_json if isinstance(diff_json, dict) else compare_legacy_vs_shadow(
        legacy_json,
        shadow_json,
    )
    conflict_types: list[str] = []

    if diff.get("intent_match") is False:
        conflict_types.append(ShadowConflictType.INTENT_MISMATCH.value)
    if diff.get("entity_match") is False:
        conflict_types.append(ShadowConflictType.ENTITY_MISMATCH.value)
    if diff.get("amount_match") is False:
        conflict_types.append(ShadowConflictType.AMOUNT_ERROR.value)
    if diff.get("direction_match") is False:
        conflict_types.append(ShadowConflictType.DIRECTION_ERROR.value)

    if not _shadow_entities(shadow_json):
        conflict_types.append(ShadowConflictType.MISSING_ENTITY.value)

    if conflict_types and _shadow_confidence(shadow_json) >= high_confidence_threshold:
        conflict_types.append(ShadowConflictType.OVERCONFIDENCE_ERROR.value)

    return list(dict.fromkeys(conflict_types))


def _shadow_entities(shadow_json: dict[str, Any]) -> list[dict[str, Any]]:
    entities = shadow_json.get("entities")
    if not isinstance(entities, list):
        return []
    return [entity for entity in entities if isinstance(entity, dict) and entity.get("name")]


def _shadow_confidence(shadow_json: dict[str, Any]) -> float:
    confidence = shadow_json.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        return 0.0
    return float(confidence)
