import json
import urllib.error
import urllib.request
from typing import Any, cast

from app.services.prompts.llm_v2_prompt import LLM_V2_PROMPT

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3:8b"

VALID_INTENTS = {"SETUP", "WORK", "FINANCIAL", "NOTE", "DOCUMENT"}
VALID_ACTIONS = {
    "ADD_ENTITY", "UPDATE_ENTITY", "WORK_LOG",
    "PAYMENT_IN", "PAYMENT_OUT", "PURCHASE_PAID",
    "DEBT_CREATED", "CHECK_PAYMENT", "NOTE",
}
VALID_ENTITY_KINDS = {"PERSON", "COMPANY", "UNKNOWN"}
VALID_PROJECT_ROLES = {"CLIENT", "DAILY_WORKER", "SKILLED_WORKER", "VENDOR", "OTHER"}
VALID_DIRECTIONS = {"IN", "OUT", "NONE"}
VALID_PAYMENT_METHODS = {"CASH", "BANK_TRANSFER", "CHECK", "OTHER"}
VALID_WORK_UNITS = {"day", "meter", "item", "project", "custom"}


class LLMv2Interpreter:
    def interpret(self, raw_text: str, project_id: int) -> dict[str, Any]:
        try:
            parsed = self._generate(raw_text, project_id)
            if not isinstance(parsed, dict):
                return self._fallback(raw_text, "model returned non-object JSON")
            return self._coerce(parsed)
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, TypeError):
            return self._fallback(raw_text, "shadow interpreter failed")

    def _generate(self, raw_text: str, project_id: int) -> Any:
        payload = json.dumps(
            {
                "model": OLLAMA_MODEL,
                "prompt": f"{LLM_V2_PROMPT}\n\nProject ID: {project_id}\nNote:\n{raw_text}",
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            ollama_body = json.loads(response.read().decode("utf-8"))
        return json.loads(ollama_body.get("response", ""))

    def _coerce(self, value: dict[str, Any]) -> dict[str, Any]:
        intent = value.get("intent")
        action = value.get("action")
        raw_financial = value.get("financial")
        raw_work = value.get("work")
        raw_note = value.get("note")
        financial = cast("dict[str, Any]", raw_financial) if isinstance(raw_financial, dict) else {}
        work = cast("dict[str, Any]", raw_work) if isinstance(raw_work, dict) else {}
        note = cast("dict[str, Any]", raw_note) if isinstance(raw_note, dict) else {}
        direction = financial.get("direction")
        unit = work.get("unit")
        due_date_text = financial.get("due_date_text")
        work_description = work.get("description")
        note_text = note.get("text")

        return {
            "intent": intent if intent in VALID_INTENTS else "NOTE",
            "action": action if action in VALID_ACTIONS else self._action_for_intent(intent),
            "entities": self._entities(value.get("entities")),
            "financial": {
                "amount": self._number_or_none(financial.get("amount")),
                "direction": direction if direction in VALID_DIRECTIONS else "NONE",
                "payment_method": (
                    financial.get("payment_method")
                    if financial.get("payment_method") in VALID_PAYMENT_METHODS
                    else None
                ),
                "due_date_text": (
                    due_date_text.strip()
                    if isinstance(due_date_text, str) and due_date_text.strip()
                    else None
                ),
            },
            "work": {
                "quantity": self._number_or_none(work.get("quantity")),
                "unit": unit if unit in VALID_WORK_UNITS else None,
                "description": (
                    work_description.strip()
                    if isinstance(work_description, str) and work_description.strip()
                    else None
                ),
            },
            "note": {
                "text": (
                    note_text.strip()
                    if isinstance(note_text, str) and note_text.strip()
                    else None
                ),
            },
            "confidence": self._confidence(value.get("confidence")),
            "ambiguity": bool(value.get("ambiguity")),
            "missing_fields": self._missing_fields(value.get("missing_fields")),
            "reasoning_summary": str(
                value.get("reasoning_summary") or value.get("reasoning") or ""
            ),
        }

    def _action_for_intent(self, intent: Any) -> str:
        if intent == "SETUP":
            return "ADD_ENTITY"
        if intent == "WORK":
            return "WORK_LOG"
        if intent == "FINANCIAL":
            return "PAYMENT_OUT"
        return "NOTE"

    def _entities(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        entities: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            kind = item.get("kind")
            project_role = item.get("project_role")
            role_detail = item.get("role_detail")
            phone = item.get("phone")
            account_number = item.get("account_number")
            daily_rate = item.get("daily_rate")
            notes = item.get("notes")
            field_updates = item.get("field_updates")
            entities.append(
                {
                    "name": name.strip(),
                    "kind": kind if kind in VALID_ENTITY_KINDS else "UNKNOWN",
                    "project_role": (
                        project_role if project_role in VALID_PROJECT_ROLES else "OTHER"
                    ),
                    "role_detail": (
                        str(role_detail).strip()
                        if isinstance(role_detail, str) and role_detail.strip()
                        else None
                    ),
                    "phone": (
                        str(phone).strip()
                        if isinstance(phone, str) and phone.strip()
                        else None
                    ),
                    "account_number": (
                        str(account_number).strip()
                        if isinstance(account_number, str) and account_number.strip()
                        else None
                    ),
                    "daily_rate": self._number_or_none(daily_rate),
                    "notes": (
                        str(notes).strip()
                        if isinstance(notes, str) and notes.strip()
                        else None
                    ),
                    "field_updates": field_updates if isinstance(field_updates, dict) else None,
                }
            )
        return entities

    def _number_or_none(self, value: Any) -> int | float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return value

    def _confidence(self, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return 0.0
        return max(0.0, min(float(value), 1.0))

    def _missing_fields(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    def _fallback(self, raw_text: str, reason: str) -> dict[str, Any]:
        return {
            "intent": "NOTE",
            "action": "NOTE",
            "entities": [],
            "financial": {
                "amount": None, "direction": "NONE",
                "payment_method": None, "due_date_text": None,
            },
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": raw_text},
            "confidence": 0.0,
            "ambiguity": True,
            "missing_fields": [],
            "reasoning_summary": f"{reason}: {raw_text}",
            "_llm_v2_failed": True,
        }
