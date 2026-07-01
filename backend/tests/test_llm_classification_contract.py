from app.services.input_normalizer import normalize_user_input
from app.services.llm_classification_contract import (
    validate_controlled_classification,
)
from app.services.llm_v2_interpreter import LLMv2Interpreter
from app.services.prompts.llm_v2_prompt import build_llm_v2_prompt
from tests.natural_input_helpers import natural_input_interpretation


def test_controlled_contract_role_before_name_daily_worker() -> None:
    normalized = normalize_user_input("کارگر روز مزد مش رحیم")
    classification = validate_controlled_classification(
        {
            "domain": "SETUP",
            "action": "CREATE_OR_UPDATE_PROFILE",
            "entity_type": "PERSON",
            "project_role": "DAILY_WORKER",
            "selected_name": "روز مزد مش رحیم",
            "role_detail": "کارگر روز مزد",
            "financial_direction": "NONE",
            "amount": None,
            "phone": None,
            "account_number": None,
            "confidence": 0.9,
        },
        normalized,
    )

    assert classification.selected_name == "مش رحیم"
    assert classification.project_role == "DAILY_WORKER"
    assert classification.domain == "SETUP"
    assert classification.action == "CREATE_OR_UPDATE_PROFILE"


def test_controlled_contract_simple_worker_keeps_role_words_out_of_name() -> None:
    normalized = normalize_user_input("کار گر ساده مش رحیم")
    classification = validate_controlled_classification(
        {
            "domain": "SETUP",
            "action": "CREATE_OR_UPDATE_PROFILE",
            "entity_type": "PERSON",
            "project_role": "DAILY_WORKER",
            "selected_name": "کار گر ساده مش رحیم",
            "role_detail": "کارگر ساده",
            "financial_direction": "NONE",
            "confidence": 0.8,
        },
        normalized,
    )

    assert classification.selected_name == "مش رحیم"
    assert classification.project_role in {"DAILY_WORKER", "OTHER"}
    assert classification.role_detail is not None
    assert "کار گر" not in classification.selected_name
    assert "ساده" not in classification.selected_name


def test_normalizer_separator_and_skilled_worker_candidates() -> None:
    separated = normalize_user_input("کارگر روز مزد: مش رحیم")
    tile = normalize_user_input("کاشی کار ریاحی")
    compact_tile = normalize_user_input("کاشیکار ریاحی")

    assert separated["separator_detected"] is True
    assert separated["name_candidates"] == ["مش رحیم"]
    assert separated["role_candidates"][0]["project_role"] == "DAILY_WORKER"
    assert tile["name_candidates"] == ["ریاحی"]
    assert tile["role_candidates"][0]["project_role"] == "SKILLED_WORKER"
    assert compact_tile["name_candidates"] == ["ریاحی"]
    assert compact_tile["role_candidates"][0]["project_role"] == "SKILLED_WORKER"


def test_contact_and_account_contract_validation() -> None:
    contact = validate_controlled_classification(
        {
            "domain": "CONTACT",
            "action": "UPDATE_PHONE",
            "entity_type": "PERSON",
            "project_role": "OTHER",
            "selected_name": "میثم",
            "financial_direction": "NONE",
            "phone": "111",
            "confidence": 0.9,
        },
        normalize_user_input("شماره تماس میثم: 09132842675"),
    )
    account = validate_controlled_classification(
        {
            "domain": "ACCOUNT",
            "action": "UPDATE_ACCOUNT",
            "entity_type": "PERSON",
            "project_role": "OTHER",
            "selected_name": "میثم",
            "financial_direction": "NONE",
            "account_number": "111",
            "confidence": 0.9,
        },
        normalize_user_input("شماره حساب میثم : 664334566666666"),
    )

    assert contact.domain == "CONTACT"
    assert contact.action == "UPDATE_PHONE"
    assert contact.selected_name == "میثم"
    assert contact.phone == "09132842675"
    assert account.domain == "ACCOUNT"
    assert account.action == "UPDATE_ACCOUNT"
    assert account.selected_name == "میثم"
    assert account.account_number == "664334566666666"


def test_malformed_llm_output_is_coerced_to_safe_values() -> None:
    normalized = normalize_user_input("کارگر روز مزد مش رحیم ۵۰۰۰ تومان")
    classification = validate_controlled_classification(
        {
            "domain": "BANANA",
            "action": "PAY_EVERYONE",
            "entity_type": "ROBOT",
            "project_role": "BOSS",
            "selected_name": "کارگر روز مزد: مش رحیم 5000",
            "financial_direction": "SIDEWAYS",
            "amount": 999,
            "confidence": 2,
        },
        normalized,
    )

    assert classification.domain == "OTHER"
    assert classification.action == "OTHER"
    assert classification.entity_type == "UNKNOWN"
    assert classification.project_role == "OTHER"
    assert classification.selected_name == "مش رحیم"
    assert classification.amount in {None, normalized["amount_candidates"][0]}
    assert classification.financial_direction == "UNKNOWN"
    assert classification.confidence == 1.0


def test_interpreter_adapts_controlled_contract_to_existing_schema() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "domain": "CONTACT",
            "action": "UPDATE_PHONE",
            "entity_type": "PERSON",
            "project_role": "OTHER",
            "selected_name": "میثم",
            "role_detail": None,
            "financial_direction": "NONE",
            "amount": None,
            "phone": "09132842675",
            "account_number": None,
            "confidence": 0.9,
        },
        "شماره تماس میثم: 09132842675",
    )

    assert result["intent"] == "SETUP"
    assert result["action"] == "UPDATE_ENTITY"
    assert result["entities"][0]["name"] == "میثم"
    assert result["entities"][0]["phone"] == "09132842675"
    assert result["entities"][0]["field_updates"]["phone"] == "09132842675"


def test_prompt_declares_strict_controlled_contract() -> None:
    prompt, _domain = build_llm_v2_prompt("کارگر روز مزد مش رحیم", project_id=1)

    assert "raw_input for reference only" in prompt
    assert "Allowed domain values:" in prompt
    assert "You are NOT allowed to invent enum values." in prompt
    assert "You are NOT allowed to invent person names." in prompt
    assert "Prefer selected_name from name_candidates." in prompt
    assert "Never include role words inside selected_name." in prompt


def test_pipeline_examples_use_validated_clean_names(client) -> None:
    project = client.post("/projects", json={"name": "controlled contract examples"}).json()

    daily = natural_input_interpretation(client, project["id"], "کارگر روز مزد: مش رحیم")
    simple = natural_input_interpretation(client, project["id"], "کار گر ساده مش رحیم")
    tile = natural_input_interpretation(client, project["id"], "کاشی کار ریاحی")
    compact_tile = natural_input_interpretation(client, project["id"], "کاشیکار ریاحی")
    contact = natural_input_interpretation(client, project["id"], "شماره تماس میثم: 09132842675")
    account = natural_input_interpretation(client, project["id"], "شماره حساب میثم : 664334566666666")

    assert daily["extracted_entities"][0]["name"] == "مش رحیم"
    assert daily["extracted_entities"][0]["project_role"] == "DAILY_WORKER"
    assert simple["extracted_entities"][0]["name"] == "مش رحیم"
    assert "ساده" not in simple["extracted_entities"][0]["name"]
    assert tile["extracted_entities"][0]["name"] == "ریاحی"
    assert tile["extracted_entities"][0]["project_role"] == "SKILLED_WORKER"
    assert compact_tile["extracted_entities"][0]["name"] == "ریاحی"
    assert compact_tile["extracted_entities"][0]["project_role"] == "SKILLED_WORKER"
    assert contact["extracted_entities"][0]["name"] == "میثم"
    assert contact["extracted_entities"][0]["phone"] == "09132842675"
    assert account["extracted_entities"][0]["name"] == "میثم"
    assert account["extracted_entities"][0]["account_number"] == "664334566666666"
