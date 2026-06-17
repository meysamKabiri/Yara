import json
import urllib.error
import urllib.request
from typing import Any

from app.services.prompts.llm_v2_prompt import LLM_V2_PROMPT

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"

VALID_INTENTS = {"SETUP", "WORK", "FINANCIAL", "NOTE"}
VALID_ENTITY_KINDS = {"PERSON", "COMPANY", "UNKNOWN"}
VALID_DIRECTIONS = {"IN", "OUT", "NONE"}
VALID_UNITS = {"day", "meter", "item", None}


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
        financial = value.get("financial") if isinstance(value.get("financial"), dict) else {}
        work = value.get("work") if isinstance(value.get("work"), dict) else {}
        direction = financial.get("direction")
        unit = work.get("unit")

        return {
            "intent": intent if intent in VALID_INTENTS else "NOTE",
            "entities": self._entities(value.get("entities")),
            "financial": {
                "amount": self._number_or_none(financial.get("amount")),
                "direction": direction if direction in VALID_DIRECTIONS else "NONE",
            },
            "work": {
                "quantity": self._number_or_none(work.get("quantity")),
                "unit": unit if unit in VALID_UNITS else None,
            },
            "confidence": self._confidence(value.get("confidence")),
            "ambiguity": bool(value.get("ambiguity")),
            "missing_fields": self._missing_fields(value.get("missing_fields")),
            "reasoning": str(value.get("reasoning") or ""),
        }

    def _entities(self, value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        entities: list[dict[str, str]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            kind = item.get("kind")
            entities.append(
                {
                    "name": name.strip(),
                    "kind": kind if kind in VALID_ENTITY_KINDS else "UNKNOWN",
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
            "entities": [],
            "financial": {"amount": None, "direction": "NONE"},
            "work": {"quantity": None, "unit": None},
            "confidence": 0.0,
            "ambiguity": True,
            "missing_fields": [],
            "reasoning": f"{reason}: {raw_text}",
        }
