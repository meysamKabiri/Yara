from __future__ import annotations

from typing import Any

import pytest

from app.services.input_normalizer import ROLE_TOKEN_MAP, normalize_user_input
from app.services.llm_classification_contract import (
    ALLOWED_ACTIONS,
    ALLOWED_DOMAINS,
    ALLOWED_ENTITY_TYPES,
    ALLOWED_FINANCIAL_DIRECTIONS,
    ALLOWED_PROJECT_ROLES,
    validate_controlled_classification,
)
from app.services.llm_v2_interpreter import LLMv2Interpreter


ROLE_WORDS = tuple(sorted(ROLE_TOKEN_MAP.keys(), key=len, reverse=True))


def _first_entity(normalized: dict[str, Any]) -> dict[str, Any] | None:
    entities = normalized.get("entities")
    if isinstance(entities, list) and entities and isinstance(entities[0], dict):
        return entities[0]
    return None


def _assert_no_role_words_in_name(name: str | None) -> None:
    if not name:
        return
    for role_word in ROLE_WORDS:
        assert role_word not in name


def _assert_normalizer_safe(text: str) -> dict[str, Any]:
    normalized = normalize_user_input(text)
    assert isinstance(normalized["clean_text"], str)
    assert isinstance(normalized["entities"], list)
    assert isinstance(normalized["facts"], list)
    assert isinstance(normalized["financials"], dict)
    assert isinstance(normalized["name_candidates"], list)
    assert isinstance(normalized["role_candidates"], list)
    assert isinstance(normalized["amount_candidates"], list)
    assert isinstance(normalized["phone_candidates"], list)
    assert isinstance(normalized["account_candidates"], list)
    assert isinstance(normalized["separator_detected"], bool)

    entity = _first_entity(normalized)
    if entity is not None:
        _assert_no_role_words_in_name(entity.get("name"))
        assert entity.get("role") in {
            "CLIENT",
            "VENDOR",
            "DAILY_WORKER",
            "SKILLED_WORKER",
            "WORKER",
            "OTHER",
        }
    financials = normalized["financials"]
    assert financials.get("amount") is None or isinstance(financials.get("amount"), int)
    assert financials.get("phone") is None or isinstance(financials.get("phone"), str)
    assert financials.get("account_number") is None or isinstance(financials.get("account_number"), str)
    return normalized


def _contract_output(
    *,
    domain: str = "SETUP",
    action: str = "CREATE_OR_UPDATE_PROFILE",
    entity_type: str = "PERSON",
    project_role: str = "OTHER",
    selected_name: str | None = None,
    role_detail: str | None = None,
    financial_direction: str = "NONE",
    amount: int | None = None,
    phone: str | None = None,
    account_number: str | None = None,
    confidence: float = 0.8,
) -> dict[str, Any]:
    return {
        "domain": domain,
        "action": action,
        "entity_type": entity_type,
        "project_role": project_role,
        "selected_name": selected_name,
        "role_detail": role_detail,
        "financial_direction": financial_direction,
        "amount": amount,
        "phone": phone,
        "account_number": account_number,
        "confidence": confidence,
    }


@pytest.mark.parametrize(
    ("text", "expected_name", "expected_role"),
    [
        ("ک ا ر ف ر م ا مش رحیم", None, None),
        ("کار فر مای مش رحیم", None, None),
        ("کارفر ما ی مش رحیم", "ی مش رحیم", "CLIENT"),
        ("گارفرما مش رحیم", "مش رحیم", "CLIENT"),
        ("صاحاب مش رحیم", "مش رحیم", "CLIENT"),
    ],
)
def test_persian_corruption_normalizer_is_safe(
    text: str,
    expected_name: str | None,
    expected_role: str | None,
) -> None:
    normalized = _assert_normalizer_safe(text)
    entity = _first_entity(normalized)
    if expected_name is not None:
        assert entity is not None
        assert entity["name"] == expected_name
        assert entity["role"] == expected_role
    else:
        assert normalized["clean_text"]


@pytest.mark.parametrize(
    ("text", "expected_name"),
    [
        ("کارگر روز مزد استاد کار مش رحیم", "مش رحیم"),
        ("مش رحیم کارگر کارفرما", "مش رحیم"),
        ("کارگر مش رحیم صاحب پروژه", "مش رحیم"),
    ],
)
def test_role_name_mixing_attacks_keep_names_clean(text: str, expected_name: str) -> None:
    normalized = _assert_normalizer_safe(text)
    entity = _first_entity(normalized)

    assert entity is not None
    assert entity["name"] == expected_name
    assert len({fact.get("value") for fact in normalized["facts"] if fact.get("type") == "ROLE_TOKEN"}) <= 1


@pytest.mark.parametrize(
    "text",
    [
        "مش رحیم هم کارگر هم مشتری پروژه",
        "مش رحیم کارفرما ولی خودش کارگره",
        "کارگر مش رحیم ولی صاحب حساب هم هست",
    ],
)
def test_ambiguous_contexts_choose_one_safe_interpretation(text: str) -> None:
    normalized = _assert_normalizer_safe(text)
    role_candidates = normalized["role_candidates"]

    assert len(role_candidates) >= 1
    entity = _first_entity(normalized)
    if entity is not None:
        assert isinstance(entity["name"], str)
        assert isinstance(entity["role"], str)


@pytest.mark.parametrize(
    ("text", "expected_amount", "selected_name", "direction"),
    [
        ("مش رحیم کارگر 1200000 گرفت", 1200000, "مش رحیم", "INCOMING"),
        ("میثم کارفرما 500000 پرداخت کرد", 500000, "میثم", "OUTGOING"),
        ("مش رحیم کارگر حقوقش 2 میلیون شد", 2000000, "مش رحیم", "UNKNOWN"),
    ],
)
def test_financial_setup_mix_validates_amount_and_clean_name(
    text: str,
    expected_amount: int,
    selected_name: str,
    direction: str,
) -> None:
    normalized = _assert_normalizer_safe(text)
    classification = validate_controlled_classification(
        _contract_output(
            domain="FINANCIAL",
            action="REGISTER_PAYMENT",
            project_role="OTHER",
            selected_name=selected_name,
            financial_direction=direction,
            amount=999999999,
        ),
        normalized,
    )

    assert classification.domain == "FINANCIAL"
    assert classification.amount == expected_amount
    assert classification.selected_name == selected_name
    _assert_no_role_words_in_name(classification.selected_name)
    assert classification.financial_direction in ALLOWED_FINANCIAL_DIRECTIONS


@pytest.mark.parametrize(
    "text",
    [
        "کارگر: مش رحیم",
        "کارگر ؛ مش رحیم",
        "کارگر - مش رحیم",
        "کارگر, مش رحیم",
    ],
)
def test_separator_variants_segment_role_and_name(text: str) -> None:
    normalized = _assert_normalizer_safe(text)
    entity = _first_entity(normalized)

    assert normalized["separator_detected"] is True
    assert entity is not None
    assert entity["name"] == "مش رحیم"


@pytest.mark.parametrize(
    ("text", "domain", "action", "field", "value"),
    [
        ("شماره تماس میثم 09132842675", "CONTACT", "UPDATE_PHONE", "phone", "09132842675"),
        (
            "شماره حساب مش رحیم 664334566666666",
            "ACCOUNT",
            "UPDATE_ACCOUNT",
            "account_number",
            "664334566666666",
        ),
    ],
)
def test_contact_account_contract_selects_valid_fields(
    text: str,
    domain: str,
    action: str,
    field: str,
    value: str,
) -> None:
    normalized = _assert_normalizer_safe(text)
    selected_name = normalized["name_candidates"][0]
    classification = validate_controlled_classification(
        _contract_output(
            domain=domain,
            action=action,
            selected_name=selected_name,
            phone=value if field == "phone" else None,
            account_number=value if field == "account_number" else None,
        ),
        normalized,
    )

    assert classification.domain == domain
    assert classification.action == action
    assert classification.selected_name == selected_name
    assert getattr(classification, field) == value
    _assert_no_role_words_in_name(classification.selected_name)


@pytest.mark.parametrize(
    "llm_output",
    [
        {"domain": "DROP_TABLE", "action": "HACK", "selected_name": "کارگر مش رحیم"},
        {"domain": "SETUP", "action": "CREATE_OR_UPDATE_PROFILE", "selected_name": "کارگر: مش رحیم 123"},
        {"entity_type": "ALIEN", "project_role": "KING", "financial_direction": "SIDEWAYS"},
        {"domain": "FINANCIAL", "action": "REGISTER_PAYMENT", "amount": 999, "selected_name": "مش رحیم"},
        {"domain": ["SETUP"], "action": {"bad": "shape"}, "selected_name": None},
    ],
)
def test_malformed_llm_output_is_sanitized(llm_output: dict[str, Any]) -> None:
    normalized = normalize_user_input("کارگر روز مزد مش رحیم 1200000 تومان")
    classification = validate_controlled_classification(llm_output, normalized)

    assert classification.domain in ALLOWED_DOMAINS
    assert classification.action in ALLOWED_ACTIONS
    assert classification.entity_type in ALLOWED_ENTITY_TYPES
    assert classification.project_role in ALLOWED_PROJECT_ROLES
    assert classification.financial_direction in ALLOWED_FINANCIAL_DIRECTIONS
    _assert_no_role_words_in_name(classification.selected_name)

    coerced = LLMv2Interpreter()._coerce(llm_output, "کارگر روز مزد مش رحیم 1200000 تومان")
    assert coerced["intent"] in {"SET_ROLE", "SETUP", "WORK", "FINANCIAL", "NOTE", "DOCUMENT"}
    assert isinstance(coerced["entities"], list)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "کارگر",
        "0913284",
        "worker مش رحیم",
        "کارگر کارگر مش رحیم",
    ],
)
def test_adversarial_edge_cases_degrade_gracefully(text: str) -> None:
    normalized = _assert_normalizer_safe(text)
    classification = validate_controlled_classification(
        _contract_output(
            domain="SETUP",
            action="CREATE_OR_UPDATE_PROFILE",
            selected_name=(normalized["name_candidates"][0] if normalized["name_candidates"] else None),
            project_role=(
                normalized["role_candidates"][0]["project_role"]
                if normalized["role_candidates"]
                else "OTHER"
            ),
        ),
        normalized,
    )

    assert classification.domain in ALLOWED_DOMAINS
    assert classification.action in ALLOWED_ACTIONS
    assert classification.project_role in ALLOWED_PROJECT_ROLES
    _assert_no_role_words_in_name(classification.selected_name)

