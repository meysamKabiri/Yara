import pytest

from app.services.llm_v2_interpreter import LLMOutputParseError, LLMv2Interpreter, _is_bare_entity


def test_qwen3_thinking_json_is_used_when_response_is_empty() -> None:
    parsed = LLMv2Interpreter()._parse_ollama_json(
        {
            "response": "",
            "thinking": '{"name": "میثم", "phone": "09123456789"}',
        }
    )

    assert parsed == {"name": "میثم", "phone": "09123456789"}


def test_response_json_is_used_before_thinking() -> None:
    parsed = LLMv2Interpreter()._parse_ollama_json(
        {
            "response": '{"intent": "SETUP", "action": "UPDATE_ENTITY"}',
            "thinking": '{"intent": "NOTE"}',
        }
    )

    assert parsed == {"intent": "SETUP", "action": "UPDATE_ENTITY"}


def test_surrounding_text_json_is_extracted() -> None:
    parsed = LLMv2Interpreter()._parse_ollama_json(
        {
            "response": 'Here is JSON:\n{"intent": "SETUP", "action": "UPDATE_ENTITY"}\nDone',
            "thinking": "",
        }
    )

    assert parsed == {"intent": "SETUP", "action": "UPDATE_ENTITY"}


def test_empty_response_and_thinking_fail_cleanly() -> None:
    with pytest.raises(LLMOutputParseError):
        LLMv2Interpreter()._parse_ollama_json({"response": "", "thinking": ""})


def test_invalid_response_and_thinking_fail_cleanly() -> None:
    with pytest.raises(LLMOutputParseError):
        LLMv2Interpreter()._parse_ollama_json(
            {"response": "not json", "thinking": "also not json"}
        )


def test_account_number_profile_update_is_repaired_from_raw_input() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "intent": "SET_ROLE",
            "action": "SET_ROLE",
            "entities": [
                {
                    "name": "میثم",
                    "kind": "PERSON",
                    "project_role": "OTHER",
                    "phone": None,
                    "account_number": None,
                    "field_updates": None,
                }
            ],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.9,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "The note provides a bank account number for میثم.",
        },
        "شماره حساب میثم 6037991234567890",
    )

    assert result["intent"] == "SETUP"
    assert result["action"] == "UPDATE_ENTITY"
    assert result["entities"][0]["account_number"] == "6037991234567890"
    assert result["entities"][0]["field_updates"]["account_number"] == "6037991234567890"


def test_account_number_profile_update_creates_entity_when_llm_returns_note() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "intent": "NOTE",
            "action": "NOTE",
            "entities": [],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": "The note provides a bank account number for میثم."},
            "confidence": 0.9,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "The note provides a bank account number.",
        },
        "شماره حساب میثم 6037991234567890",
    )

    assert result["intent"] == "SETUP"
    assert result["action"] == "UPDATE_ENTITY"
    assert result["entities"][0]["name"] == "میثم"
    assert result["entities"][0]["account_number"] == "6037991234567890"
    assert result["entities"][0]["field_updates"]["account_number"] == "6037991234567890"


def test_phone_profile_update_is_repaired_from_raw_input() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "intent": "SET_ROLE",
            "action": "SET_ROLE",
            "entities": [
                {
                    "name": "میثم",
                    "kind": "PERSON",
                    "project_role": "OTHER",
                    "phone": None,
                    "account_number": None,
                    "field_updates": None,
                }
            ],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.9,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "The note provides a phone number for میثم.",
        },
        "شماره تماس میثم 09123456789",
    )

    assert result["intent"] == "SETUP"
    assert result["action"] == "UPDATE_ENTITY"
    assert result["entities"][0]["phone"] == "09123456789"
    assert result["entities"][0]["field_updates"]["phone"] == "09123456789"


def test_phone_profile_update_creates_entity_when_llm_returns_note() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "intent": "NOTE",
            "action": "NOTE",
            "entities": [],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": "The note provides a phone number for میثم."},
            "confidence": 0.9,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "The note provides a phone number.",
        },
        "شماره تماس میثم 09123456789",
    )

    assert result["intent"] == "SETUP"
    assert result["action"] == "UPDATE_ENTITY"
    assert result["entities"][0]["name"] == "میثم"
    assert result["entities"][0]["phone"] == "09123456789"
    assert result["entities"][0]["field_updates"]["phone"] == "09123456789"


def test_role_assignment_does_not_get_account_number() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "intent": "SET_ROLE",
            "action": "SET_ROLE",
            "entities": [
                {
                    "name": "میثم کبیری",
                    "kind": "PERSON",
                    "project_role": "CLIENT",
                    "phone": None,
                    "account_number": None,
                    "field_updates": None,
                }
            ],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.9,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "Role assignment.",
        },
        "میثم کبیری کارفرمای پروژه است",
    )

    assert result["intent"] == "SET_ROLE"
    assert result["action"] == "SET_ROLE"
    assert result["entities"][0]["account_number"] is None


def test_plain_note_stays_note_without_profile_digits() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "intent": "NOTE",
            "action": "NOTE",
            "entities": [],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": "یادداشت کلی برای پروژه"},
            "confidence": 0.9,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "Plain note.",
        },
        "یادداشت کلی برای پروژه",
    )

    assert result["intent"] == "NOTE"
    assert result["action"] == "NOTE"
    assert result["entities"] == []


def test_bare_entity_with_role_detail_wraps_to_set_role() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "name": "جعفری",
            "kind": "PERSON",
            "project_role": "SKILLED_WORKER",
            "role_detail": "لوله کش",
            "phone": None,
            "account_number": None,
            "daily_rate": None,
            "notes": None,
            "field_updates": None,
        },
        "جعفری لوله کش به پروژه اضافه شد",
    )

    assert result["intent"] == "SET_ROLE"
    assert result["action"] == "SET_ROLE"
    assert len(result["entities"]) == 1
    assert result["entities"][0]["name"] == "جعفری"
    assert result["entities"][0]["project_role"] == "SKILLED_WORKER"
    assert result["entities"][0]["role_detail"] == "لوله کش"


def test_bare_entity_with_account_number_wraps_to_entity_update() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "name": "میثم",
            "kind": "PERSON",
            "project_role": "OTHER",
            "account_number": "6037991234567890",
            "phone": None,
            "daily_rate": None,
            "notes": None,
            "field_updates": {"account_number": "6037991234567890"},
        },
        "شماره حساب میثم 6037991234567890",
    )

    assert result["intent"] == "SETUP"
    assert result["action"] == "UPDATE_ENTITY"
    assert len(result["entities"]) == 1
    assert result["entities"][0]["account_number"] == "6037991234567890"


def test_bare_entity_with_phone_wraps_to_entity_update() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "name": "میثم",
            "kind": "PERSON",
            "project_role": "OTHER",
            "phone": "09123456789",
            "account_number": None,
            "daily_rate": None,
            "notes": None,
            "field_updates": {"phone": "09123456789"},
        },
        "شماره تماس میثم 09123456789",
    )

    assert result["intent"] == "SETUP"
    assert result["action"] == "UPDATE_ENTITY"
    assert result["entities"][0]["phone"] == "09123456789"


def test_bare_entity_without_name_or_wrapper_keys_stays_untouched() -> None:
    value = {"project_role": "CLIENT", "role_detail": "some detail"}
    assert not _is_bare_entity(value)
    result = LLMv2Interpreter()._coerce(value, "some text")
    assert result["intent"] == "NOTE"


def test_full_schema_goes_through_unmodified() -> None:
    value = {
        "intent": "SET_ROLE",
        "action": "SET_ROLE",
        "entities": [{"name": "test", "kind": "PERSON", "project_role": "CLIENT"}],
        "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
        "work": {"quantity": None, "unit": None, "description": None},
        "note": {"text": None},
        "confidence": 0.9,
        "ambiguity": False,
        "missing_fields": [],
        "reasoning_summary": "test",
    }
    result = LLMv2Interpreter()._coerce(value, "test text")
    assert result["intent"] == "SET_ROLE"
    assert result["action"] == "SET_ROLE"
    assert len(result["entities"]) == 1


def test_bare_entity_with_incoming_financial_repairs_to_financial() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "name": "میثم کبیری",
            "kind": "PERSON",
            "project_role": "OTHER",
            "phone": None,
            "account_number": None,
            "daily_rate": None,
            "notes": None,
            "field_updates": None,
        },
        "از میثم کبیری 50 میلیون گرفتم",
    )
    assert result["intent"] == "FINANCIAL"
    assert result["action"] == "PAYMENT_IN"
    assert result["financial"]["amount"] == 50000000
    assert result["financial"]["direction"] == "IN"


def test_bare_entity_with_outgoing_financial_repairs_to_financial() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "name": "علی احمدی",
            "kind": "PERSON",
            "project_role": "OTHER",
            "phone": None,
            "account_number": None,
            "daily_rate": None,
            "notes": None,
            "field_updates": None,
        },
        "به علی احمدی 5 میلیون دادم",
    )
    assert result["intent"] == "FINANCIAL"
    assert result["action"] == "PAYMENT_OUT"
    assert result["financial"]["amount"] == 5000000
    assert result["financial"]["direction"] == "OUT"


def test_bare_entity_with_purchase_repairs_to_purchase_paid() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "name": "هادی پور",
            "kind": "PERSON",
            "project_role": "OTHER",
            "phone": None,
            "account_number": None,
            "daily_rate": None,
            "notes": None,
            "field_updates": None,
        },
        "از هادی پور 25 میلیون سیم خریدم و پرداخت کردم",
    )
    assert result["intent"] == "FINANCIAL"
    assert result["action"] == "PURCHASE_PAID"
    assert result["financial"]["amount"] == 25000000
    assert result["financial"]["direction"] == "OUT"


def test_bare_entity_with_role_text_stays_set_role() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "name": "میثم کبیری",
            "kind": "PERSON",
            "project_role": "CLIENT",
            "phone": None,
            "account_number": None,
            "daily_rate": None,
            "notes": None,
            "field_updates": None,
        },
        "میثم کبیری کارفرمای پروژه است",
    )
    assert result["intent"] == "SET_ROLE"
    assert result["action"] == "SET_ROLE"
    assert result["entities"][0]["name"] == "میثم کبیری"


def test_bare_entity_with_profile_fields_still_trumps_financial_signal() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "name": "مش رحیم",
            "kind": "PERSON",
            "project_role": "DAILY_WORKER",
            "phone": None,
            "account_number": None,
            "daily_rate": 1200000,
            "notes": None,
            "field_updates": {"daily_rate": 1200000},
        },
        "دستمزد روزانه مش رحیم 1200000 تومان است",
    )
    assert result["intent"] == "SETUP"
    assert result["action"] == "UPDATE_ENTITY"
