from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.role_registry import project_role_values
from app.models.core import InterpretationFeedback, InterpretationFeedbackErrorType
from app.services.input_normalizer import ROLE_TOKEN_MAP, normalize_user_input
from app.services.persian_money_engine import normalize_text

ERROR_TYPES = [error.value for error in InterpretationFeedbackErrorType]
KNOWN_PROJECT_ROLES = project_role_values()
PROFILE_TERMS = {
    "شماره",
    "تماس",
    "موبایل",
    "تلفن",
    "حساب",
    "کارت",
    "شبا",
    "حقوق",
    "دستمزد",
    "پرداخت",
    "گرفت",
    "داد",
    "واریز",
    "پروژه",
}


def analyze_feedback_intelligence(
    db: Session,
    *,
    project_id: int,
    days: int = 7,
    unknown_role_threshold: int = 2,
) -> dict[str, Any]:
    records = _feedback_records(db, project_id=project_id, days=days)
    error_distribution = _error_distribution(records)
    top_problem_patterns = _top_problem_patterns(records)
    unknown_role_candidates = _unknown_role_candidates(
        records,
        threshold=unknown_role_threshold,
    )
    normalization_failures = _normalization_failures(records)
    disagreement_rate = _disagreement_rate(records)
    recommendations = _system_recommendations(
        error_distribution=error_distribution,
        top_problem_patterns=top_problem_patterns,
        unknown_role_candidates=unknown_role_candidates,
        normalization_failures=normalization_failures,
    )

    return {
        "project_id": project_id,
        "time_window": f"last_{days}_days",
        "error_distribution": error_distribution,
        "top_problem_patterns": top_problem_patterns,
        "unknown_role_candidates": unknown_role_candidates,
        "normalization_failures": normalization_failures,
        "llm_disagreement_rate": disagreement_rate,
        "system_recommendations": recommendations,
    }


def _feedback_records(
    db: Session,
    *,
    project_id: int,
    days: int,
) -> list[InterpretationFeedback]:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    return list(
        db.scalars(
            select(InterpretationFeedback)
            .where(InterpretationFeedback.project_id == project_id)
            .where(InterpretationFeedback.created_at >= cutoff)
            .order_by(InterpretationFeedback.created_at.desc(), InterpretationFeedback.id.desc())
        )
    )


def _error_distribution(records: list[InterpretationFeedback]) -> dict[str, int]:
    counts = {error_type: 0 for error_type in ERROR_TYPES}
    for record in records:
        for error_type in record.error_types or []:
            if error_type in counts:
                counts[error_type] += 1
    return counts


def _top_problem_patterns(records: list[InterpretationFeedback], limit: int = 10) -> list[dict[str, Any]]:
    errored_inputs = [record.raw_input for record in records if record.error_types]
    clusters: list[dict[str, Any]] = []
    for raw_input in errored_inputs:
        key = _pattern_key(raw_input)
        match = _matching_cluster(clusters, key)
        if match is None:
            clusters.append(
                {
                    "pattern": _pattern_label(raw_input),
                    "key": key,
                    "examples": [raw_input],
                    "frequency": 1,
                }
            )
        else:
            match["examples"].append(raw_input)
            match["frequency"] += 1
            match["pattern"] = _best_pattern_label(match["examples"])

    ranked = sorted(clusters, key=lambda item: (-item["frequency"], item["pattern"]))[:limit]
    return [
        {
            "pattern": cluster["pattern"],
            "frequency": cluster["frequency"],
            "suggested_fix": _suggested_pattern_fix(cluster["examples"]),
        }
        for cluster in ranked
    ]


def _unknown_role_candidates(
    records: list[InterpretationFeedback],
    *,
    threshold: int,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    categories: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        final_entities = _entities(record.user_final_state)
        for entity in final_entities:
            role = _entity_role(entity)
            if role not in KNOWN_PROJECT_ROLES:
                continue
            phrase = _unknown_role_phrase(record.raw_input, entity)
            if phrase is None:
                continue
            counts[phrase] += 1
            categories[phrase][role] += 1

    results = []
    for phrase, frequency in counts.items():
        if frequency < threshold:
            continue
        suggested_category = categories[phrase].most_common(1)[0][0]
        results.append(
            {
                "text": phrase,
                "frequency": frequency,
                "suggested_category": suggested_category,
            }
        )
    return sorted(results, key=lambda item: (-item["frequency"], item["text"]))


def _normalization_failures(records: list[InterpretationFeedback], limit: int = 20) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        if not record.error_types:
            continue
        normalized = normalize_user_input(record.raw_input)
        final_entity = _first_entity(record.user_final_state)
        reason = _normalization_failure_reason(record, normalized, final_entity)
        if reason is None:
            continue
        key = (record.raw_input, reason)
        if key in seen:
            continue
        seen.add(key)
        failures.append({"input_example": record.raw_input, "failure_reason": reason})
        if len(failures) >= limit:
            break
    return failures


def _disagreement_rate(records: list[InterpretationFeedback]) -> float:
    if not records:
        return 0.0
    disagreements = sum(1 for record in records if record.error_types)
    return round(disagreements / len(records), 4)


def _system_recommendations(
    *,
    error_distribution: dict[str, int],
    top_problem_patterns: list[dict[str, Any]],
    unknown_role_candidates: list[dict[str, Any]],
    normalization_failures: list[dict[str, str]],
) -> list[str]:
    recommendations: list[str] = []
    if unknown_role_candidates:
        top = unknown_role_candidates[0]
        recommendations.append(
            f"review ROLE_MAP expansion for '{top['text']}' as {top['suggested_category']}"
        )
    if top_problem_patterns:
        recommendations.append("review normalization rules for recurring corrupted input patterns")
    if error_distribution.get("WRONG_DOMAIN", 0) > 0:
        recommendations.append("inspect controlled domain classification examples with WRONG_DOMAIN feedback")
    if error_distribution.get("WRONG_ROLE", 0) > 0:
        recommendations.append("inspect role evidence extraction for WRONG_ROLE feedback")
    if normalization_failures:
        recommendations.append("add deterministic normalization tests for observed failure examples")
    return recommendations


def _matching_cluster(clusters: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    for cluster in clusters:
        cluster_key = str(cluster["key"])
        if key == cluster_key:
            return cluster
        if _token_similarity(key, cluster_key) >= 0.78:
            return cluster
        if _levenshtein_similarity(key, cluster_key) >= 0.82:
            return cluster
    return None


def _pattern_key(value: str) -> str:
    normalized = normalize_text(value or "")
    normalized = normalized.replace("\u200c", " ")
    normalized = re.sub(r"[^\w\u0600-\u06FF\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    compact = normalized.replace(" ", "")
    return compact or normalized


def _pattern_label(value: str) -> str:
    normalized = normalize_text(value or "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or value


def _best_pattern_label(examples: list[str]) -> str:
    labels = [_pattern_label(example) for example in examples]
    return min(labels, key=lambda label: (len(label.replace(" ", "")), len(label), label))


def _suggested_pattern_fix(examples: list[str]) -> str:
    if any(_has_suspicious_spacing(example) for example in examples):
        return "add spacing normalization rule"
    if any(_has_role_like_text(example) for example in examples):
        return "review role token normalization"
    return "review recurring interpretation feedback pattern"


def _unknown_role_phrase(raw_input: str, entity: dict[str, Any]) -> str | None:
    name = str(entity.get("name") or "").strip()
    text = normalize_text(raw_input or "")
    if name:
        text = text.replace(name, " ")
    text = re.sub(r"[۰-۹٠-٩0-9]+", " ", text)
    for token in sorted(ROLE_TOKEN_MAP, key=len, reverse=True):
        text = text.replace(token, " ")
    for term in PROFILE_TERMS:
        text = text.replace(term, " ")
    text = re.sub(r"[^\w\u0600-\u06FF\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 3:
        return None
    if text in ROLE_TOKEN_MAP:
        return None
    return _restore_ascii_acronyms(text)


def _normalization_failure_reason(
    record: InterpretationFeedback,
    normalized: dict[str, Any],
    final_entity: dict[str, Any] | None,
) -> str | None:
    errors = set(record.error_types or [])
    if final_entity is None:
        return None
    final_role = _entity_role(final_entity)
    final_name = str(final_entity.get("name") or "").strip()
    name_candidates = normalized.get("name_candidates") or []
    role_candidates = normalized.get("role_candidates") or []

    if "WRONG_ROLE" in errors and final_role in KNOWN_PROJECT_ROLES and not role_candidates:
        return "role token not recognized"
    if "WRONG_ENTITY" in errors and final_name and final_name not in name_candidates:
        return "clean name candidate not produced"
    if _has_suspicious_spacing(record.raw_input):
        return "spacing corruption not normalized"
    if "MISSING_EXTRACTION" in errors:
        return "expected field missing from normalized evidence"
    return None


def _entities(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("entities") or payload.get("extracted_entities") or []
    return [entity for entity in raw if isinstance(entity, dict)] if isinstance(raw, list) else []


def _first_entity(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    entities = _entities(payload)
    return entities[0] if entities else None


def _entity_role(entity: dict[str, Any]) -> str | None:
    role = entity.get("project_role") or entity.get("role") or entity.get("type")
    return str(role).upper() if role is not None else None


def _restore_ascii_acronyms(value: str) -> str:
    return " ".join(
        token.upper()
        if re.fullmatch(r"[a-z]{2,5}", token)
        else token
        for token in value.split()
    )


def _has_suspicious_spacing(value: str) -> bool:
    normalized = normalize_text(value or "")
    compact = normalized.replace(" ", "")
    return any(token.replace(" ", "") in compact and token not in normalized for token in ROLE_TOKEN_MAP)


def _has_role_like_text(value: str) -> bool:
    normalized = normalize_text(value or "")
    return any(token in normalized for token in ROLE_TOKEN_MAP)


def _token_similarity(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _levenshtein_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    max_len = max(len(left), len(right))
    if max_len == 0:
        return 1.0
    return 1.0 - (_levenshtein_distance(left, right) / max_len)


def _levenshtein_distance(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (left_char != right_char)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]
