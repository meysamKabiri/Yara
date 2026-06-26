"""Tests for same-input entity linking in multi-event processing.

When a multi-line input contains a full entity name in one chunk (e.g. "میثم کبیری")
and partial name references in subsequent chunks (e.g. "میثم"), the system should
resolve the partial names to the full name within the same input context.

This also verifies that structured_interpretation.entities stays in sync with
extracted_entities after resolution.
"""

from fastapi.testclient import TestClient
import pytest
from tests.natural_input_helpers import natural_input_interpretations, natural_input_interpretation


def _assert_entity_consistent(pi: dict, index: int = 0) -> None:
    """Assert that extracted_entities[index] and structured_interpretation.entities[index] agree."""
    entities = pi.get("extracted_entities", [])
    assert isinstance(entities, list) and len(entities) > index
    si = pi.get("structured_interpretation")
    assert si is not None, "structured_interpretation is missing"
    assert isinstance(si, dict)
    si_entities = si.get("entities")
    assert isinstance(si_entities, list), "structured_interpretation.entities is not a list"
    assert len(si_entities) > index, (
        f"structured_interpretation.entities has {len(si_entities)} items, need index {index}"
    )
    extracted = entities[index]
    structured = si_entities[index]
    assert isinstance(extracted, dict), f"extracted_entities[{index}] is not a dict"
    assert isinstance(structured, dict), f"structured_interpretation.entities[{index}] is not a dict"
    assert extracted.get("name") == structured.get("name"), (
        f"Name mismatch: extracted='{extracted.get('name')}' vs structured='{structured.get('name')}'"
    )
    assert extracted.get("project_role") == structured.get("project_role"), (
        f"project_role mismatch: extracted='{extracted.get('project_role')}' vs "
        f"structured='{structured.get('project_role')}'"
    )


def _mock_llm_v2(result: dict) -> dict:
    return result


def test_same_input_full_name_resolved_for_phone_chunk(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Phone update chunk resolves partial name 'میثم' to full name 'میثم کبیری'."""
    project = client.post("/projects", json={"name": "same-input-phone"}).json()
    project_id = project["id"]

    # Mock LLM to return three events: role setup, phone update, account update
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "events": [
                {
                    "intent": "SET_ROLE",
                    "action": "SET_ROLE",
                    "entities": [{"name": "میثم کبیری", "kind": "PERSON", "project_role": "CLIENT"}],
                    "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
                    "work": {"quantity": None, "unit": None, "description": None},
                    "note": {"text": None},
                    "confidence": 0.95,
                    "ambiguity": False,
                    "missing_fields": [],
                    "reasoning_summary": "میثم کبیری کارفرمای پروژه است",
                    "matched_text": "میثم کبیری کارفرمای پروژه است",
                },
                {
                    "intent": "SETUP",
                    "action": "UPDATE_ENTITY",
                    "entities": [{"name": "میثم", "field_updates": {"phone": "09123456789"}}],
                    "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
                    "work": {"quantity": None, "unit": None, "description": None},
                    "note": {"text": None},
                    "confidence": 0.9,
                    "ambiguity": False,
                    "missing_fields": [],
                    "reasoning_summary": "شماره تماس میثم 09123456789",
                    "matched_text": "شماره تماس میثم 09123456789",
                },
                {
                    "intent": "SETUP",
                    "action": "UPDATE_ENTITY",
                    "entities": [{"name": "میثم", "field_updates": {"account_number": "6037991234567890"}}],
                    "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
                    "work": {"quantity": None, "unit": None, "description": None},
                    "note": {"text": None},
                    "confidence": 0.9,
                    "ambiguity": False,
                    "missing_fields": [],
                    "reasoning_summary": "شماره حساب میثم 6037991234567890",
                    "matched_text": "شماره حساب میثم 6037991234567890",
                },
            ],
        }),
    )

    pis = natural_input_interpretations(
        client,
        project_id,
        "میثم کبیری کارفرمای پروژه است\nشماره تماس میثم 09123456789\nشماره حساب میثم 6037991234567890",
    )
    assert len(pis) == 3

    # First interpretation: SET_ROLE for میثم کبیری
    assert pis[0]["semantic_action"] == "SET_ROLE"
    _assert_entity_consistent(pis[0])
    entities0 = pis[0]["extracted_entities"]
    assert entities0 is not None and len(entities0) > 0
    assert entities0[0]["name"] == "میثم کبیری"
    assert entities0[0]["project_role"] == "CLIENT"

    # Second interpretation: phone update should resolve to میثم کبیری
    _assert_entity_consistent(pis[1])
    entities1 = pis[1]["extracted_entities"]
    assert entities1 is not None and len(entities1) > 0
    assert entities1[0]["name"] == "میثم کبیری", (
        f"Expected 'میثم کبیری', got '{entities1[0]['name']}'"
    )
    assert entities1[0].get("field_updates", {}).get("phone") == "09123456789"
    # Also check structured_interpretation preserves field_updates
    si1 = pis[1]["structured_interpretation"]
    assert si1["entities"][0]["field_updates"]["phone"] == "09123456789"
    # Role should inherit from the resolved entity
    assert entities1[0].get("project_role") in ("CLIENT", None)

    # Third interpretation: account update should resolve to میثم کبیری
    _assert_entity_consistent(pis[2])
    entities2 = pis[2]["extracted_entities"]
    assert entities2 is not None and len(entities2) > 0
    assert entities2[0]["name"] == "میثم کبیری", (
        f"Expected 'میثم کبیری', got '{entities2[0]['name']}'"
    )
    assert entities2[0].get("field_updates", {}).get("account_number") == "6037991234567890"
    # Also check structured_interpretation preserves field_updates
    si2 = pis[2]["structured_interpretation"]
    assert si2["entities"][0]["field_updates"]["account_number"] == "6037991234567890"
    assert entities2[0].get("project_role") in ("CLIENT", None)


def test_same_input_ambiguity_blocks_auto_resolution(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """When a partial name matches multiple full names, do not auto-resolve."""
    project = client.post("/projects", json={"name": "same-input-ambig"}).json()
    project_id = project["id"]

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "events": [
                {
                    "intent": "SET_ROLE",
                    "action": "SET_ROLE",
                    "entities": [{"name": "میثم کبیری", "kind": "PERSON", "project_role": "CLIENT"}],
                    "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
                    "work": {"quantity": None, "unit": None, "description": None},
                    "note": {"text": None},
                    "confidence": 0.95,
                    "ambiguity": False,
                    "missing_fields": [],
                    "reasoning_summary": "میثم کبیری کارفرمای پروژه است",
                    "matched_text": "میثم کبیری کارفرمای پروژه است",
                },
                {
                    "intent": "SET_ROLE",
                    "action": "SET_ROLE",
                    "entities": [{"name": "میثم رضایی", "kind": "PERSON", "project_role": "VENDOR"}],
                    "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
                    "work": {"quantity": None, "unit": None, "description": None},
                    "note": {"text": None},
                    "confidence": 0.95,
                    "ambiguity": False,
                    "missing_fields": [],
                    "reasoning_summary": "میثم رضایی پیمانکار پروژه است",
                    "matched_text": "میثم رضایی پیمانکار پروژه است",
                },
                {
                    "intent": "SETUP",
                    "action": "UPDATE_ENTITY",
                    "entities": [{"name": "میثم", "field_updates": {"phone": "09123456789"}}],
                    "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
                    "work": {"quantity": None, "unit": None, "description": None},
                    "note": {"text": None},
                    "confidence": 0.9,
                    "ambiguity": False,
                    "missing_fields": [],
                    "reasoning_summary": "شماره تماس میثم 09123456789",
                    "matched_text": "شماره تماس میثم 09123456789",
                },
            ],
        }),
    )

    pis = natural_input_interpretations(
        client,
        project_id,
        "میثم کبیری کارفرمای پروژه است\nمیثم رضایی پیمانکار پروژه است\nشماره تماس میثم 09123456789",
    )
    # The system may produce additional fallback interpretations beyond the 3 expected.
    # Filter to focus on the SET_ROLE and profile update ones.
    assert len(pis) >= 3

    # Every interpretation must have consistent extracted_entities and structured_interpretation
    for pi in pis:
        _assert_entity_consistent(pi)

    # Collect entity names from extracted_entities across all interpretations
    entity_names: list[str] = []
    for pi in pis:
        entities = pi.get("extracted_entities")
        if entities and len(entities) > 0:
            name = entities[0].get("name", "")
            if name:
                entity_names.append(name)

    # Should include both full names
    assert "میثم کبیری" in entity_names, (
        f"میثم کبیری not found in entity names: {entity_names}"
    )
    assert "میثم رضایی" in entity_names, (
        f"میثم رضایی not found in entity names: {entity_names}"
    )

    # The phone update should NOT be auto-resolved to either full name
    # because "میثم" matches both میثم کبیری and میثم رضایی
    assert "میثم" in entity_names, (
        f"'میثم' should remain unresolved (not attached to either full name), "
        f"got: {entity_names}"
    )
    assert entity_names.count("میثم") >= 1, (
        f"Expected at least one unresolved 'میثم', got: {entity_names}"
    )


def test_same_input_confirmation_creates_single_person(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirming all three interpretations creates only one person with all fields."""
    project = client.post("/projects", json={"name": "same-input-confirm"}).json()
    project_id = project["id"]

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "events": [
                {
                    "intent": "SET_ROLE",
                    "action": "SET_ROLE",
                    "entities": [{"name": "میثم کبیری", "kind": "PERSON", "project_role": "CLIENT"}],
                    "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
                    "work": {"quantity": None, "unit": None, "description": None},
                    "note": {"text": None},
                    "confidence": 0.95,
                    "ambiguity": False,
                    "missing_fields": [],
                    "reasoning_summary": "میثم کبیری کارفرمای پروژه است",
                    "matched_text": "میثم کبیری کارفرمای پروژه است",
                },
                {
                    "intent": "SETUP",
                    "action": "UPDATE_ENTITY",
                    "entities": [{"name": "میثم", "field_updates": {"phone": "09123456789"}}],
                    "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
                    "work": {"quantity": None, "unit": None, "description": None},
                    "note": {"text": None},
                    "confidence": 0.9,
                    "ambiguity": False,
                    "missing_fields": [],
                    "reasoning_summary": "شماره تماس میثم 09123456789",
                    "matched_text": "شماره تماس میثم 09123456789",
                },
                {
                    "intent": "SETUP",
                    "action": "UPDATE_ENTITY",
                    "entities": [{"name": "میثم", "field_updates": {"account_number": "6037991234567890"}}],
                    "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
                    "work": {"quantity": None, "unit": None, "description": None},
                    "note": {"text": None},
                    "confidence": 0.9,
                    "ambiguity": False,
                    "missing_fields": [],
                    "reasoning_summary": "شماره حساب میثم 6037991234567890",
                    "matched_text": "شماره حساب میثم 6037991234567890",
                },
            ],
        }),
    )

    pis = natural_input_interpretations(
        client,
        project_id,
        "میثم کبیری کارفرمای پروژه است\nشماره تماس میثم 09123456789\nشماره حساب میثم 6037991234567890",
    )
    assert len(pis) == 3

    # Confirm first interpretation (SET_ROLE)
    confirm1 = client.post(f"/pending-interpretations/{pis[0]['id']}/confirm", json={
        "create_new": True,
    })
    assert confirm1.status_code == 200

    # After confirming first, میثم کبیری should exist
    workers = client.get(f"/projects/{project_id}/workers").json()
    assert len(workers) == 1
    assert workers[0]["name"] == "میثم کبیری"
    assert workers[0]["type"] == "CLIENT"

    # Confirm second interpretation (phone update) - should update existing entity
    confirm2 = client.post(f"/pending-interpretations/{pis[1]['id']}/confirm", json={
        "entity_id": workers[0]["id"],
        "confirmed": True,
    })
    assert confirm2.status_code == 200

    # After confirm, entity should now have phone
    workers = client.get(f"/projects/{project_id}/workers").json()
    assert len(workers) == 1, f"Expected 1 worker, got {len(workers)}"
    assert workers[0]["name"] == "میثم کبیری"
    assert workers[0]["phone"] == "09123456789"

    # Confirm third interpretation (account update)
    confirm3 = client.post(f"/pending-interpretations/{pis[2]['id']}/confirm", json={
        "entity_id": workers[0]["id"],
        "confirmed": True,
    })
    assert confirm3.status_code == 200

    # Final check: one person with all fields
    workers = client.get(f"/projects/{project_id}/workers").json()
    assert len(workers) == 1, f"Expected 1 worker, got {len(workers)}"
    assert workers[0]["name"] == "میثم کبیری"
    assert workers[0]["type"] == "CLIENT"
    assert workers[0]["phone"] == "09123456789"
    assert workers[0]["account_number"] == "6037991234567890", (
        f"Expected account 6037991234567890, got {workers[0].get('account_number')}"
    )
